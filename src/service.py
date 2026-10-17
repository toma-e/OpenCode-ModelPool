"""Service applicatif : chargement, sélection, budget, export et synchronisation.

Cette couche est la seule à connaître les chemins de fichiers et les effets de bord.
Le CLI et l'interface web l'appellent sans dupliquer la logique métier.
"""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from datetime import datetime, timezone

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]

from src.budget import AgentBudgetReport, FleetBudgetReport, simulate_fleet_budget
from src.exporter import (
    build_modelpool_report_data,
    build_opencode_config,
    parse_json_or_jsonc,
)
from src.fetcher import (
    create_backup,
    fetch_openrouter_models,
    sync_models_from_all_providers,
    sync_models_from_openrouter,
    write_json_atomic,
)
from src.providers.detector import (
    ProviderCredentials,
    detect_provider_credentials,
)
from src.providers.ollama import get_ollama_models
from src.providers.access import (
    ProviderAccess,
    probe_provider_access,
    read_provider_access,
    resolve_verified_access,
    write_provider_access,
)
from src.providers.router import (
    DEFAULT_PROVIDER_PRIORITY,
    DIRECT_CHANNELS,
    PROVIDER_ALIASES,
    ExecutionTarget,
    resolve_model_execution_target,
)
from src.selector import (
    AgentRequirement,
    Model,
    SelectionResult,
    is_non_llm_model,
    resolve_model_for_agent,
)

DEFAULT_EXPORT_RELATIVE = Path("config") / "opencode.json"


@dataclass(frozen=True)
class FleetReport:
    """Rapport structuré d'attribution pour l'ensemble du parc d'agents."""

    models: list[Model]
    agents: list[AgentRequirement]
    results: list[SelectionResult]
    budget: FleetBudgetReport
    catalogue_updated_at: Optional[str]
    diagnostics: list[str]
    provider_priority: list[str] = field(default_factory=lambda: list(DEFAULT_PROVIDER_PRIORITY))
    execution_targets: list[Optional[ExecutionTarget]] = field(default_factory=list)
    fallback_chains: dict[str, list[str]] = field(default_factory=dict)
    # {fournisseur: {"verified": bool, "model_count": int, "checked_at": str|None}}
    access_summary: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationResult:
    """Résultat d'une action d'écriture ou de recalcul, destiné à l'UI."""

    ok: bool
    message: str
    report: Optional[FleetReport] = None


def _load_json(path: Path, label: str) -> dict[str, object]:
    """Charge un objet JSON et contextualise les erreurs de lecture."""
    try:
        with path.open(encoding="utf-8") as file:
            data: object = json.load(file)
    except FileNotFoundError as error:
        raise ValueError(f"{label} introuvable : {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} invalide ({path}) : JSON mal formé à la ligne {error.lineno}.") from error
    except OSError as error:
        raise ValueError(f"Lecture impossible de {label} ({path}) : {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{label} invalide ({path}) : un objet JSON est attendu.")
    return data


def load_data(models_path: Path, agents_path: Path) -> tuple[list[Model], list[AgentRequirement]]:
    """Charge et valide les catalogues de modèles et d'agents."""
    models, _updated, agents, _priority = _load_catalogue_and_agents(models_path, agents_path)
    return models, agents


def _load_catalogue_and_agents(
    models_path: Path,
    agents_path: Path,
) -> tuple[list[Model], Optional[str], list[AgentRequirement], list[str]]:
    models_document = _load_json(models_path, "Catalogue de modèles")
    agents_document = _load_json(agents_path, "Configuration des agents")
    raw_models = models_document.get("models", [])
    raw_agents = agents_document.get("agents", [])
    raw_priority = agents_document.get("provider_priority")
    provider_priority: list[str] = list(DEFAULT_PROVIDER_PRIORITY)
    if isinstance(raw_priority, list) and all(isinstance(x, str) and x for x in raw_priority):
        provider_priority = [x.strip() for x in raw_priority]

    if not isinstance(raw_models, list):
        raise ValueError(f"Catalogue de modèles invalide ({models_path}) : 'models' doit être une liste.")
    if not isinstance(raw_agents, list):
        raise ValueError(f"Configuration des agents invalide ({agents_path}) : 'agents' doit être une liste.")
    try:
        models = [
            Model.from_dict(item, f"modèle #{index}")
            for index, item in enumerate(raw_models, start=1)
            if isinstance(item, dict)
        ]
        if len(models) != len(raw_models):
            raise ValueError("un modèle doit être un objet JSON")
        agents = [
            AgentRequirement.from_dict(item, f"agent #{index}")
            for index, item in enumerate(raw_agents, start=1)
            if isinstance(item, dict)
        ]
        if len(agents) != len(raw_agents):
            raise ValueError("un agent doit être un objet JSON")
    except ValueError as error:
        raise ValueError(f"Configuration invalide : {error}") from error
    updated = models_document.get("last_updated")
    catalogue_updated_at = updated if isinstance(updated, str) else None
    return models, catalogue_updated_at, agents, provider_priority


def _model_payload(model: Model) -> dict[str, Any]:
    return {
        "id": model.id,
        "provider": model.provider,
        "tier": model.tier,
        "cost_input_per_m": model.cost_input_per_m,
        "cost_output_per_m": model.cost_output_per_m,
        "total_cost_per_m": model.total_cost_per_m,
        "context_window": model.context_window,
        "supports_tools": model.supports_tools,
        "complexity_score": model.complexity_score,
        "supports_vision": model.supports_vision,
        "supports_reasoning": model.supports_reasoning,
        "is_free": model.is_free,
    }


def _budget_payload(report: AgentBudgetReport) -> dict[str, Any]:
    return {
        "model_id": report.model_id,
        "tier": report.tier,
        "estimated_input_tokens": report.estimated_input_tokens,
        "estimated_output_tokens": report.estimated_output_tokens,
        "monthly_input_cost": report.monthly_input_cost,
        "monthly_output_cost": report.monthly_output_cost,
        "monthly_total_cost": report.monthly_total_cost,
        "max_budget": report.max_budget,
        "budget_exceeded": report.budget_exceeded,
        "quota_warning": report.quota_warning,
    }


def serialize_report(report: FleetReport) -> dict[str, Any]:
    """Sérialise un rapport de flotte pour l'API HTTP."""
    budget_by_agent = {item.agent_name: item for item in report.budget.agent_reports}
    assignments: list[dict[str, Any]] = []
    for index, (agent, result) in enumerate(zip(report.agents, report.results)):
        if result.model is None:
            status = "unassigned"
        elif agent.force_model:
            status = "forced"
        elif result.is_fallback:
            status = "fallback"
        else:
            status = "exact"
        agent_budget = budget_by_agent.get(agent.name)
        target = report.execution_targets[index] if index < len(report.execution_targets) else None
        target_payload = {
            "channel_provider": target.channel_provider,
            "formatted_model_id": target.formatted_model_id,
            "is_local": target.is_local,
            "description_label": target.description_label,
            "cost_in": target.effective_cost_input_per_m,
            "cost_out": target.effective_cost_output_per_m,
            "access_verified": target.access_verified,
        } if target else None

        assignments.append(
            {
                "name": agent.name,
                "description": agent.description,
                "status": status,
                "is_fallback": result.is_fallback,
                "force_model": agent.force_model,
                "reason": result.reason,
                "model": _model_payload(result.model) if result.model else None,
                "execution_target": target_payload,
                "alternatives": [_model_payload(model) for model in result.candidates[1:]],
                "budget": _budget_payload(agent_budget) if agent_budget else None,
                "constraints": {
                    "min_complexity": agent.min_complexity,
                    "max_complexity": agent.max_complexity,
                    "requires_tools": agent.requires_tools,
                    "prefer_free": agent.prefer_free,
                    "min_context_window": agent.min_context_window,
                    "allowed_providers": agent.allowed_providers,
                    "excluded_providers": agent.excluded_providers,
                    "max_monthly_budget": agent.max_monthly_budget,
                    "sort_strategy": agent.sort_strategy,
                    "allow_free": agent.allow_free,
                    "requires_vision": agent.requires_vision,
                    "requires_reasoning": agent.requires_reasoning,
                    "prefer_tier1": agent.prefer_tier1,
                },
            }
        )
    return {
        "catalogue": {
            "total_models": len(report.models),
            "last_updated": report.catalogue_updated_at,
        },
        "budget": {
            "total_monthly_cost": report.budget.total_monthly_cost,
            "total_tokens": report.budget.total_tokens,
            "free_tier_savings": report.budget.free_tier_savings,
            "has_warnings": report.budget.has_budget_warnings,
        },
        "provider_priority": list(report.provider_priority),
        "fallback_chains": report.fallback_chains,
        "access_summary": report.access_summary,
        "assignments": assignments,
        "diagnostics": list(report.diagnostics),
    }


class ApplicationService:
    """Orchestration locale du catalogue, de la sélection et des écritures."""

    def __init__(
        self,
        base_dir: Path,
        models_path: Optional[Path] = None,
        agents_path: Optional[Path] = None,
        access_path: Optional[Path] = None,
    ) -> None:
        self.base_dir = base_dir
        self.models_path = models_path if models_path is not None else (base_dir / "data" / "models.json")
        self.agents_path = agents_path if agents_path is not None else (base_dir / "config" / "agents_requirements.json")
        self.access_path = access_path if access_path is not None else (base_dir / "data" / "provider_access.json")
        self.default_export_path = base_dir / DEFAULT_EXPORT_RELATIVE
        self._lock = threading.RLock()
        self._lock_path = base_dir / "data" / ".modelpool.lock"

    @contextlib.contextmanager
    def _file_lock(self) -> Iterator[None]:
        """Verrou inter-processus utilisant fcntl.flock (POSIX) ou msvcrt.locking (Windows)."""
        if fcntl is None and msvcrt is None:
            yield
            return
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fd = lock_file.fileno()
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                elif msvcrt is not None:
                    lock_file.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    try:
                        if fcntl is not None:
                            fcntl.flock(fd, fcntl.LOCK_UN)
                        elif msvcrt is not None:
                            lock_file.seek(0)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
        except OSError:
            # Si le système de fichiers refuse le verrouillage (ex: share distant incompatible), fallback
            yield

    def resolve_export_path(self, requested: str | Path | None = None) -> Path:
        """Résout le chemin d'export OpenCode relativement à la racine du projet ou au répertoire utilisateur (~)."""
        if requested is None:
            return self.default_export_path
        target = Path(requested).expanduser()
        return target if target.is_absolute() else self.base_dir / target

    def build_report(
        self,
        allow_fallback: bool = True,
        filter_by_keys: bool = False,
        custom_priority: Optional[list[str]] = None,
    ) -> FleetReport:
        """Charge les fichiers et calcule les attributions et le budget."""
        with self._lock:
            return self._build_report_unlocked(
                allow_fallback,
                filter_by_keys=filter_by_keys,
                custom_priority=custom_priority,
            )

    def _build_report_unlocked(
        self,
        allow_fallback: bool,
        filter_by_keys: bool = False,
        custom_priority: Optional[list[str]] = None,
    ) -> FleetReport:
        models, updated, agents, default_priority = _load_catalogue_and_agents(self.models_path, self.agents_path)
        diagnostics: list[str] = []
        priority = list(custom_priority) if custom_priority else list(default_priority)

        # Détection des credentials et modèles Ollama
        creds = detect_provider_credentials(project_dir=self.base_dir)
        ollama_models = get_ollama_models() if creds.get("ollama") and creds["ollama"].is_available else []

        # Modèles réellement accessibles avec chaque clé directe (cache vérifié)
        cached_access = read_provider_access(self.access_path)
        direct_access, access_diagnostics = resolve_verified_access(
            cached_access, creds, list(DIRECT_CHANNELS.keys())
        )
        diagnostics.extend(access_diagnostics)
        access_summary = self._build_access_summary(creds, cached_access, direct_access)

        route_cache: dict[str, ExecutionTarget] = {}

        def _route(model: Model) -> ExecutionTarget:
            cached = route_cache.get(model.id)
            if cached is None:
                cached = resolve_model_execution_target(
                    reference_model=model,
                    provider_priority=priority,
                    credentials=creds,
                    ollama_models=ollama_models,
                    direct_access=direct_access,
                )
                route_cache[model.id] = cached
            return cached

        normalized_priority = [PROVIDER_ALIASES.get(p.lower(), p.lower()) for p in priority]

        def _channel_index(target: ExecutionTarget) -> int:
            channel = PROVIDER_ALIASES.get(target.channel_provider.lower(), target.channel_provider.lower())
            return normalized_priority.index(channel) if channel in normalized_priority else len(normalized_priority)

        # Filtrage optionnel : ne garder que les modèles exécutables par un canal réellement disponible
        if filter_by_keys:
            openrouter_ok = bool(creds.get("openrouter") and creds["openrouter"].is_available)
            initial_count = len(models)
            models = [m for m in models if self._is_executable(_route(m), m, openrouter_ok)]
            excluded_count = initial_count - len(models)
            if excluded_count > 0:
                diagnostics.append(
                    f"Filtrage par clés actives : {excluded_count} modèle(s) masqué(s) "
                    "(aucun canal disponible ne peut les exécuter avec vos clés)."
                )

        # Priorité des canaux : un modèle exécutable via un canal prioritaire (ex: crédits gratuits
        # Mistral/Google) est préféré à tout modèle d'un canal suivant.
        channel_rank = {m.id: _channel_index(_route(m)) for m in models}
        results = [
            resolve_model_for_agent(
                agent, models, allow_fallback=allow_fallback, channel_rank=channel_rank
            )
            for agent in agents
        ]

        # Résolution des canaux d'exécution selon l'ordre de priorité des clés
        execution_targets: list[Optional[ExecutionTarget]] = []
        adjusted_results: list[SelectionResult] = []

        for res in results:
            if res.model:
                target = _route(res.model)
                execution_targets.append(target)
                # Si le modèle est dérouté sur Ollama local, ajuster le coût à 0.0 pour le budget
                effective_model = res.model
                if target.is_local:
                    effective_model = Model(
                        id=target.formatted_model_id,
                        provider="ollama",
                        tier="free_tier",
                        cost_input_per_m=0.0,
                        cost_output_per_m=0.0,
                        context_window=res.model.context_window,
                        supports_tools=res.model.supports_tools,
                        complexity_score=res.model.complexity_score,
                        supports_vision=res.model.supports_vision,
                        supports_reasoning=res.model.supports_reasoning,
                    )
                adjusted_results.append(
                    SelectionResult(
                        agent_name=res.agent_name,
                        model=effective_model,
                        is_fallback=res.is_fallback,
                        candidates=res.candidates,
                        reason=res.reason,
                    )
                )
            else:
                execution_targets.append(None)
                adjusted_results.append(res)

        # Chaîne de repli par agent (limites de débit / quotas) : modèles suivants sur des canaux distincts
        fallback_chains: dict[str, list[str]] = {}
        for res, target in zip(results, execution_targets):
            if res.model is None or target is None:
                continue
            seen_channels = {target.channel_provider}
            seen_ids = {target.formatted_model_id}
            chain: list[str] = []
            for candidate in res.candidates[1:]:
                cand_target = _route(candidate)
                if cand_target.channel_provider in seen_channels or cand_target.formatted_model_id in seen_ids:
                    continue
                seen_channels.add(cand_target.channel_provider)
                seen_ids.add(cand_target.formatted_model_id)
                chain.append(cand_target.formatted_model_id)
                if len(chain) >= 3:
                    break
            fallback_chains[res.agent_name] = chain

        budget = simulate_fleet_budget(adjusted_results, agents)
        if not models:
            diagnostics.append("Le catalogue de modèles est vide.")
        if not agents:
            diagnostics.append("Aucun agent n'est déclaré dans la configuration.")
        if updated is None:
            diagnostics.append("La date de mise à jour du catalogue est absente.")
        else:
            try:
                # Normalisation du parsing ISO avec fallback si fuseau horaire
                updated_dt = datetime.fromisoformat(updated)
                now_dt = datetime.now(timezone.utc) if updated_dt.tzinfo else datetime.now()
                days_old = (now_dt - updated_dt).days
                if days_old > 14:
                    diagnostics.append(
                        f"Le catalogue date de plus de {days_old} jours ({updated[:10]}). "
                        "Pensez à exécuter 'python3 main.py --sync'."
                    )
            except (ValueError, TypeError):
                pass
        unassigned = [result.agent_name for result in adjusted_results if result.model is None]
        if unassigned:
            diagnostics.append("Agents sans modèle : " + ", ".join(unassigned) + ".")
        return FleetReport(
            models=models,
            agents=agents,
            results=adjusted_results,
            budget=budget,
            catalogue_updated_at=updated,
            diagnostics=diagnostics,
            provider_priority=priority,
            execution_targets=execution_targets,
            fallback_chains=fallback_chains,
            access_summary=access_summary,
        )

    def _build_access_summary(
        self,
        creds: Mapping[str, ProviderCredentials],
        cached_access: Mapping[str, ProviderAccess],
        direct_access: Mapping[str, frozenset[str]],
    ) -> dict[str, dict[str, Any]]:
        summary: dict[str, dict[str, Any]] = {}
        for prov in DIRECT_CHANNELS:
            cred = creds.get(prov)
            entry = cached_access.get(prov)
            verified = prov in direct_access
            count = len(direct_access[prov]) if verified else (len(entry.model_ids) if entry else 0)
            summary[prov] = {
                "available": bool(cred and cred.is_available),
                "verified": verified,
                "model_count": count,
                "status": entry.status if entry else "not_checked",
                "checked_at": entry.checked_at if entry else None,
                "error": entry.error if entry else None,
            }
        return summary

    def _is_executable(self, target: ExecutionTarget, model: Model, openrouter_available: bool) -> bool:
        """Détermine si un modèle peut réellement être exécuté par un canal disponible."""
        if target.is_local:
            return True
        if target.access_verified:
            return True
        if target.channel_provider == "openrouter":
            return openrouter_available or model.is_free
        # Canaux directs sans accès vérifié : non garantis
        return False

    def refresh_provider_access(self, allow_fallback: bool = True) -> OperationResult:
        """Interroge les APIs directes pour mettre à jour la liste réelle des modèles accessibles par clé."""
        with self._lock, self._file_lock():
            try:
                creds = detect_provider_credentials(project_dir=self.base_dir)
                access_map = probe_provider_access(creds, project_dir=self.base_dir)
                write_provider_access(self.access_path, access_map)
                report = self._build_report_unlocked(allow_fallback=allow_fallback)
                summary_parts = [
                    f"{p}: {len(item.model_ids)} modèle(s)"
                    for p, item in sorted(access_map.items())
                    if item.status == "ok"
                ]
                msg = f"Accès vérifié pour : {', '.join(summary_parts) if summary_parts else 'aucun fournisseur'}"
                return OperationResult(True, msg, report)
            except Exception as error:
                return OperationResult(False, f"Erreur lors de la vérification des accès : {error}")

    def build_report_result(
        self,
        allow_fallback: bool = True,
        filter_by_keys: bool = False,
        custom_priority: Optional[list[str]] = None,
    ) -> OperationResult:
        """Calcule un rapport en traduisant les erreurs de chargement."""
        try:
            report = self.build_report(
                allow_fallback,
                filter_by_keys=filter_by_keys,
                custom_priority=custom_priority,
            )
        except ValueError as error:
            return OperationResult(False, str(error))
        return OperationResult(True, "Rapport calculé.", report)

    def get_providers_status(self) -> Dict[str, ProviderCredentials]:
        """Renvoie le statut des identifiants et clés pour chaque fournisseur."""
        return detect_provider_credentials(project_dir=self.base_dir)

    def get_provider_priority(self) -> list[str]:
        """Renvoie l'ordre de priorité des fournisseurs actuellement configuré."""
        try:
            _m, _u, _a, priority = _load_catalogue_and_agents(self.models_path, self.agents_path)
            return priority
        except Exception:
            return list(DEFAULT_PROVIDER_PRIORITY)

    def set_provider_priority(
        self,
        new_priority: list[str],
        allow_fallback: bool = True,
        filter_by_keys: bool = False,
    ) -> OperationResult:
        """Met à jour l'ordre de priorité des fournisseurs dans la configuration et recalcule."""
        if not isinstance(new_priority, list) or not all(isinstance(x, str) and x.strip() for x in new_priority):
            return OperationResult(False, "La priorité des fournisseurs doit être une liste de chaînes non vides.")

        cleaned_priority = [x.strip().lower() for x in new_priority]

        with self._lock, self._file_lock():
            try:
                agents_data = _load_json(self.agents_path, "Configuration des agents")
                agents_data["provider_priority"] = cleaned_priority
                create_backup(self.agents_path)
                write_json_atomic(self.agents_path, agents_data)

                report = self._build_report_unlocked(
                    allow_fallback=allow_fallback,
                    filter_by_keys=filter_by_keys,
                    custom_priority=cleaned_priority,
                )
                return OperationResult(True, "Ordre de priorité des fournisseurs mis à jour.", report)
            except Exception as error:
                return OperationResult(False, f"Erreur lors de la mise à jour de la priorité : {error}")

    def sync_catalogue(
        self,
        allow_fallback: bool = True,
        multi_provider: bool = False,
        include_ollama: bool = True,
        filter_by_keys: bool = False,
    ) -> OperationResult:
        """Synchronise le catalogue (OpenRouter seul ou multi-providers si demandé) puis recalcule le rapport.

        Par défaut, conserve la synchronisation OpenRouter pour la compatibilité ascendante,
        ou multi-providers si multi_provider=True.
        """
        if not multi_provider:
            try:
                raw_models = fetch_openrouter_models()
            except Exception as error:
                return OperationResult(False, f"Échec de la synchronisation : {error}")

            with self._lock, self._file_lock():
                try:
                    count, backup = sync_models_from_openrouter(
                        self.models_path,
                        raw_models=raw_models,
                    )
                except Exception as error:
                    return OperationResult(False, f"Échec de la synchronisation : {error}")
                try:
                    report = self._build_report_unlocked(allow_fallback, filter_by_keys=filter_by_keys)
                except ValueError as error:
                    return OperationResult(False, str(error))
                message = f"{count} modèles synchronisés avec succès dans {self.models_path}"
                if backup:
                    message += f" (sauvegarde : {backup})"
                return OperationResult(True, message, report)

        # Mode multi-fournisseurs complet
        with self._lock, self._file_lock():
            try:
                count, backup, summary = sync_models_from_all_providers(
                    self.models_path,
                    include_ollama=include_ollama,
                    project_dir=self.base_dir,
                )
                sources_str = ", ".join(f"{k}: {v}" for k, v in summary.items() if v > 0)
                message = f"{count} modèles synchronisés avec succès ({sources_str})"
                # Mise à jour du cache d'accès réel des clés
                creds = detect_provider_credentials(project_dir=self.base_dir)
                access_map = probe_provider_access(creds, project_dir=self.base_dir)
                write_provider_access(self.access_path, access_map)
            except Exception as error:
                return OperationResult(False, f"Échec de la synchronisation : {error}")

            try:
                report = self._build_report_unlocked(allow_fallback, filter_by_keys=filter_by_keys)
            except ValueError as error:
                return OperationResult(False, str(error))

            if backup:
                message += f" (sauvegarde : {backup})"
            return OperationResult(True, message, report)

    def load_base_opencode_config(self) -> dict[str, Any] | None:
        """Charge la configuration de base OpenCode depuis le dossier Ressources si disponible.

        Raises:
            ValueError: Si un fichier de configuration de base trouvé est corrompu ou invalide.
        """
        candidates = [
            self.base_dir / "Ressources" / "opencode.jsonc",
            self.base_dir / "Ressources" / "opencode.json",
            self.base_dir / "ressources" / "opencode.jsonc",
            self.base_dir / "ressources" / "opencode.json",
        ]
        for candidate in candidates:
            if candidate.is_file():
                try:
                    return parse_json_or_jsonc(candidate.read_text(encoding="utf-8"))
                except ValueError as error:
                    raise ValueError(f"Fichier de base OpenCode invalide ({candidate}) : {error}") from error
        return None

    def export_config(
        self,
        path: str | Path | None = None,
        allow_fallback: bool = True,
        base_config: dict[str, Any] | None = None,
        default_provider_prefix: str = "openrouter",
        create_backup_file: bool = True,
        report_output_path: Optional[Path] = None,
        filter_by_keys: bool = False,
        custom_priority: Optional[list[str]] = None,
    ) -> OperationResult:
        """Exporte la configuration OpenCode et le rapport d'audit sous verrou d'écriture."""
        with self._lock, self._file_lock():
            try:
                report = self._build_report_unlocked(
                    allow_fallback,
                    filter_by_keys=filter_by_keys,
                    custom_priority=custom_priority,
                )
                effective_base = (
                    base_config if base_config is not None else self.load_base_opencode_config()
                )
                target_path = self.resolve_export_path(path)
                # L'identifiant exporté est celui du canal retenu (ex: mistral/..., google/...)
                export_results = [
                    replace(res, model=replace(res.model, id=target.formatted_model_id))
                    if res.model is not None and target is not None
                    else res
                    for res, target in zip(
                        report.results,
                        list(report.execution_targets) + [None] * len(report.results),
                    )
                ]
                config_data = build_opencode_config(
                    export_results,
                    report.agents,
                    base_config=effective_base,
                    default_provider_prefix=default_provider_prefix,
                )

                if create_backup_file and target_path.exists():
                    create_backup(target_path)

                write_json_atomic(target_path, config_data)

                target_report_path = (
                    report_output_path
                    if report_output_path is not None
                    else target_path.parent / "modelpool-report.json"
                )
                report_data = build_modelpool_report_data(
                    export_results, report.agents, fallback_chains=report.fallback_chains
                )
                write_json_atomic(target_report_path, report_data)

                exported = target_path.resolve()
            except ValueError as error:
                return OperationResult(False, str(error))
            except OSError as error:
                return OperationResult(False, f"Écriture de l'export impossible : {error}")
            return OperationResult(True, f"Configuration OpenCode exportée : {exported}", report)

    def update_agent_requirement(
        self,
        agent_name: str,
        updates: dict[str, Any],
        allow_fallback: bool = True,
    ) -> OperationResult:
        """Met à jour les exigences d'un agent avec validation, backup et écriture atomique."""
        with self._lock, self._file_lock():
            try:
                raw_data = _load_json(self.agents_path, "Exigences des agents")
                agents_list = raw_data.get("agents")
                if not isinstance(agents_list, list):
                    return OperationResult(False, "Format de configuration invalide : 'agents' doit être une liste.")

                target_dict: Optional[dict[str, Any]] = None
                for item in agents_list:
                    if isinstance(item, dict) and item.get("name") == agent_name:
                        target_dict = item
                        break

                if target_dict is None:
                    return OperationResult(False, f"Agent '{agent_name}' introuvable.")

                # On applique les modifications sur une copie pour valider
                merged = dict(target_dict)
                merged.update(updates)
                # Validation stricte via AgentRequirement
                validated_req = AgentRequirement.from_dict(merged, f"agent '{agent_name}'")

                # Reconstruire le dictionnaire propre pour le JSON en retirant les clés None optionnelles
                new_dict: dict[str, Any] = {
                    "name": validated_req.name,
                    "description": validated_req.description,
                    "min_complexity": validated_req.min_complexity,
                    "max_complexity": validated_req.max_complexity,
                    "requires_tools": validated_req.requires_tools,
                    "prefer_free": validated_req.prefer_free,
                    "allow_free": validated_req.allow_free,
                    "sort_strategy": validated_req.sort_strategy,
                    "requires_vision": validated_req.requires_vision,
                    "requires_reasoning": validated_req.requires_reasoning,
                    "prefer_tier1": validated_req.prefer_tier1,
                }
                if validated_req.min_context_window is not None:
                    new_dict["min_context_window"] = validated_req.min_context_window
                if validated_req.allowed_providers is not None:
                    new_dict["allowed_providers"] = validated_req.allowed_providers
                if validated_req.excluded_providers is not None:
                    new_dict["excluded_providers"] = validated_req.excluded_providers
                if validated_req.force_model is not None:
                    new_dict["force_model"] = validated_req.force_model
                if validated_req.mode is not None:
                    new_dict["mode"] = validated_req.mode
                if validated_req.estimated_tokens_input > 0:
                    new_dict["estimated_tokens_input"] = validated_req.estimated_tokens_input
                if validated_req.estimated_tokens_output > 0:
                    new_dict["estimated_tokens_output"] = validated_req.estimated_tokens_output
                if validated_req.max_monthly_budget is not None:
                    new_dict["max_monthly_budget"] = validated_req.max_monthly_budget

                # Remplacement dans la liste
                index = agents_list.index(target_dict)
                agents_list[index] = new_dict

                # Backup puis écriture atomique
                create_backup(self.agents_path)
                write_json_atomic(self.agents_path, {"agents": agents_list})

                # Recalcul du rapport
                report = self._build_report_unlocked(allow_fallback)
                return OperationResult(True, f"Exigences de l'agent '{agent_name}' mises à jour.", report)
            except ValueError as error:
                return OperationResult(False, f"Validation échouée : {error}")
            except Exception as error:
                return OperationResult(False, f"Erreur lors de la mise à jour : {error}")

    def import_models_from_json(
        self,
        json_path: Path,
        allow_fallback: bool = True,
        filter_by_keys: bool = False,
    ) -> OperationResult:
        """Valide et fusionne de nouveaux modèles (ex: sortie de Deep Research) dans models.json sous verrou."""
        if not json_path.is_file():
            return OperationResult(False, f"Fichier source introuvable : {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                raw_payload = json.load(f)
        except Exception as error:
            return OperationResult(False, f"Lecture impossible du fichier JSON ({json_path}) : {error}")

        raw_candidates: list[dict[str, Any]]
        if isinstance(raw_payload, list):
            raw_candidates = [m for m in raw_payload if isinstance(m, dict)]
        elif isinstance(raw_payload, dict) and isinstance(raw_payload.get("models"), list):
            raw_candidates = [m for m in raw_payload["models"] if isinstance(m, dict)]
        else:
            return OperationResult(False, "Format invalide : une liste d'objets modèles ou un objet avec 'models' est attendu.")

        if not raw_candidates:
            return OperationResult(False, "Aucun modèle trouvé dans le fichier fourni.")

        validated_candidates: list[Model] = []
        rejected_non_llm: list[str] = []
        validation_errors: list[str] = []

        for idx, item in enumerate(raw_candidates, start=1):
            m_id = str(item.get("id", f"candidat #{idx}"))
            if is_non_llm_model(m_id):
                rejected_non_llm.append(m_id)
                continue
            try:
                model_obj = Model.from_dict(item, context=f"candidat #{idx} ({m_id})")
                validated_candidates.append(model_obj)
            except Exception as err:
                validation_errors.append(f"{m_id}: {err}")

        if validation_errors:
            sample_errors = "; ".join(validation_errors[:3])
            if len(validation_errors) > 3:
                sample_errors += f" (+{len(validation_errors) - 3} autres)"
            return OperationResult(
                False,
                f"Validation échouée sur {len(validation_errors)} modèle(s) : {sample_errors}",
            )

        if not validated_candidates:
            return OperationResult(
                False,
                f"Tous les modèles fournis ont été exclus car non-LLM ({len(rejected_non_llm)} exclus).",
            )

        with self._lock, self._file_lock():
            try:
                with open(self.models_path, "r", encoding="utf-8") as f:
                    catalogue_data = json.load(f)
            except Exception as error:
                return OperationResult(False, f"Lecture impossible du catalogue actuel ({self.models_path}) : {error}")

            models_dict: dict[str, dict[str, Any]] = {
                m["id"]: m for m in catalogue_data.get("models", []) if isinstance(m, dict) and "id" in m
            }

            added_count = 0
            updated_count = 0

            for m in validated_candidates:
                m_dict = {
                    "id": m.id,
                    "provider": m.provider,
                    "tier": m.tier,
                    "cost_input_per_m": m.cost_input_per_m,
                    "cost_output_per_m": m.cost_output_per_m,
                    "context_window": m.context_window,
                    "supports_tools": m.supports_tools,
                    "complexity_score": m.complexity_score,
                    "supports_vision": m.supports_vision,
                    "supports_reasoning": m.supports_reasoning,
                }
                if m.id in models_dict:
                    models_dict[m.id] = m_dict
                    updated_count += 1
                else:
                    models_dict[m.id] = m_dict
                    added_count += 1

            # Tri déterministe
            sorted_models = sorted(models_dict.values(), key=lambda x: str(x["id"]))
            catalogue_data["models"] = sorted_models
            catalogue_data["total_models"] = len(sorted_models)
            catalogue_data["last_updated"] = datetime.now(timezone.utc).isoformat()

            backup_path, _ = create_backup(self.models_path)
            write_json_atomic(self.models_path, catalogue_data)

            report = self._build_report_unlocked(allow_fallback=allow_fallback, filter_by_keys=filter_by_keys)
            msg_parts = [f"Intégration réussie : {added_count} ajouté(s), {updated_count} mis à jour."]
            if rejected_non_llm:
                msg_parts.append(f"{len(rejected_non_llm)} modèle(s) non-LLM ignoré(s).")
            if backup_path:
                msg_parts.append(f"Backup créé : {backup_path.name}.")
            return OperationResult(True, " ".join(msg_parts), report)



