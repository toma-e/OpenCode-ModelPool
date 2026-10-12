"""Service applicatif : chargement, sélection, budget, export et synchronisation.

Cette couche est la seule à connaître les chemins de fichiers et les effets de bord.
Le CLI et l'interface web l'appellent sans dupliquer la logique métier.
"""

from __future__ import annotations

import contextlib
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

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
    build_modelscope_report_data,
    build_opencode_config,
    parse_json_or_jsonc,
)
from src.fetcher import (
    create_backup,
    fetch_openrouter_models,
    sync_models_from_openrouter,
    write_json_atomic,
)
from src.selector import AgentRequirement, Model, SelectionResult, resolve_model_for_agent

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
    models, _updated, agents = _load_catalogue_and_agents(models_path, agents_path)
    return models, agents


def _load_catalogue_and_agents(
    models_path: Path,
    agents_path: Path,
) -> tuple[list[Model], Optional[str], list[AgentRequirement]]:
    models_document = _load_json(models_path, "Catalogue de modèles")
    agents_document = _load_json(agents_path, "Configuration des agents")
    raw_models = models_document.get("models", [])
    raw_agents = agents_document.get("agents", [])
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
    return models, catalogue_updated_at, agents


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
    for agent, result in zip(report.agents, report.results):
        if result.model is None:
            status = "unassigned"
        elif agent.force_model:
            status = "forced"
        elif result.is_fallback:
            status = "fallback"
        else:
            status = "exact"
        agent_budget = budget_by_agent.get(agent.name)
        assignments.append(
            {
                "name": agent.name,
                "description": agent.description,
                "status": status,
                "is_fallback": result.is_fallback,
                "force_model": agent.force_model,
                "reason": result.reason,
                "model": _model_payload(result.model) if result.model else None,
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
    ) -> None:
        self.base_dir = base_dir
        self.models_path = models_path if models_path is not None else (base_dir / "data" / "models.json")
        self.agents_path = agents_path if agents_path is not None else (base_dir / "config" / "agents_requirements.json")
        self.default_export_path = base_dir / DEFAULT_EXPORT_RELATIVE
        self._lock = threading.RLock()
        self._lock_path = base_dir / "data" / ".modelscope.lock"

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
        """Résout le chemin d'export OpenCode relativement à la racine du projet."""
        if requested is None:
            return self.default_export_path
        target = Path(requested)
        return target if target.is_absolute() else self.base_dir / target

    def build_report(self, allow_fallback: bool = True) -> FleetReport:
        """Charge les fichiers et calcule les attributions et le budget."""
        with self._lock:
            return self._build_report_unlocked(allow_fallback)

    def _build_report_unlocked(self, allow_fallback: bool) -> FleetReport:
        models, updated, agents = _load_catalogue_and_agents(self.models_path, self.agents_path)
        results = [
            resolve_model_for_agent(agent, models, allow_fallback=allow_fallback) for agent in agents
        ]
        budget = simulate_fleet_budget(results, agents)
        diagnostics: list[str] = []
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
        unassigned = [result.agent_name for result in results if result.model is None]
        if unassigned:
            diagnostics.append("Agents sans modèle : " + ", ".join(unassigned) + ".")
        return FleetReport(models, agents, results, budget, updated, diagnostics)

    def build_report_result(self, allow_fallback: bool = True) -> OperationResult:
        """Calcule un rapport en traduisant les erreurs de chargement."""
        try:
            report = self.build_report(allow_fallback)
        except ValueError as error:
            return OperationResult(False, str(error))
        return OperationResult(True, "Rapport calculé.", report)

    def sync_catalogue(self, allow_fallback: bool = True) -> OperationResult:
        """Synchronise OpenRouter puis recalcule le rapport.

        L'appel réseau est réalisé hors verrou (évite le Head-of-Line Blocking),
        puis l'écriture atomique et le recalcul s'effectuent sous verrou exclusif.
        """
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
                report = self._build_report_unlocked(allow_fallback)
            except ValueError as error:
                return OperationResult(False, str(error))
            message = f"{count} modèles synchronisés avec succès dans {self.models_path}"
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
    ) -> OperationResult:
        """Exporte la configuration OpenCode et le rapport d'audit sous verrou d'écriture."""
        with self._lock, self._file_lock():
            try:
                report = self._build_report_unlocked(allow_fallback)
                effective_base = (
                    base_config if base_config is not None else self.load_base_opencode_config()
                )
                target_path = self.resolve_export_path(path)
                config_data = build_opencode_config(
                    report.results,
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
                    else target_path.parent / "modelscope-report.json"
                )
                report_data = build_modelscope_report_data(report.results, report.agents)
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


