"""Module de synchronisation et de génération du catalogue de modèles via l'API OpenRouter.

Ce module permet de :
1. Récupérer dynamiquement la liste publique des modèles OpenRouter.
2. Déduire les capacités, tarifications et scores de complexité.
3. Sauvegarder le catalogue dans data/models.json tout en créant une sauvegarde (backup)
   horodatée de la version précédente.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from src.selector import Model, is_non_llm_model

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
MAX_TIMESTAMPED_BACKUPS = 20

# Regex pré-compilées pour l'estimation de complexité
NANO_RE = re.compile(r"(?:^|[-_/:])(?:nano|micro|tiny)(?:$|[-_/:])")
MINI_RE = re.compile(r"(?:^|[-_/:])mini(?:$|[-_/:])")
LITE_RE = re.compile(r"(?:^|[-_/:])lite(?:$|[-_/:])")
PARAM_SIZE_RE = re.compile(r"(?<![a-z0-9])(?:(\d+)x)?(\d+(?:\.\d+)?)b(?![a-z0-9])")
REASONING_MINI_RE = re.compile(r"(?:^|[-_/:])o[134]-mini")
FLAGSHIP_REASONING_RE = re.compile(r"(?:^|[-_/:])(?:o1|o3|o4|r1|deepseek-r1)(?:$|[-_/:])")
GPT_FLAGSHIP_RE = re.compile(r"(?:^|[-_/:])gpt-[45](?:\.\d+)?(?:$|[-_/:])")


def estimate_complexity_score(model_id: str, prompt_cost_per_m: float) -> int:
    """Estime un score de complexité (1 à 5) basé sur l'identifiant et le tarif du modèle.

    Heuristique :
    - 5 (Expert / Raisonnement complexe) : Modèles phares (Opus, Sonnet, o1, o3, R1, 405B, GPT-4, etc.)
    - 4 (Avancé / Codeur lourd) : Modèles intermédiaires-hauts (70B, 72B, Codestral, Mistral-Large, etc.)
    - 3 (Moyen / Généraliste rapide) : Modèles légers rapides (Flash, Haiku, 8B, 14B, 32B, etc.)
    - 2 (Compact / Tâches simples) : Petits modèles (Flash-lite, 7B, 3B, Mini, Lite)
    - 1 (Ultra-léger / Embarqué) : Micro modèles (1B, 0.5B, Nano)
    """
    m_id = model_id.lower()

    # Détection des modificateurs de taille
    has_nano = bool(NANO_RE.search(m_id))
    has_mini = bool(MINI_RE.search(m_id))
    has_lite = bool("flash-lite" in m_id or LITE_RE.search(m_id))

    # Extraction des tailles de paramètres (supportant le format standard et le format MoE NxMb)
    parameter_sizes: list[float] = []
    for num_experts_str, param_str in PARAM_SIZE_RE.findall(m_id):
        base_size = float(param_str)
        if num_experts_str:
            # Pour un MoE (ex: 8x22b, 4x7b), la masse totale de paramètres est experts * base
            parameter_sizes.append(int(num_experts_str) * base_size)
        else:
            parameter_sizes.append(base_size)

    # Priorité 1 : Ultra-légers (nano, micro, tiny, <= 1.5B)
    if has_nano or any(size <= 1.5 for size in parameter_sizes):
        return 1

    # Détection des variantes compactes de raisonnement (ex: o1-mini, o3-mini, o4-mini)
    is_reasoning_mini = bool(REASONING_MINI_RE.search(m_id))

    # Priorité 2 : Petits modèles (< 7.5B, mini, lite)
    if (has_mini and not is_reasoning_mini) or has_lite or any(1.5 < size <= 7.5 for size in parameter_sizes):
        return 2

    # Variantes compactes de raisonnement (score 3 ou 4 si 'high')
    if is_reasoning_mini:
        return 4 if "high" in m_id else 3

    # Priorité 5 : Modèles phares / raisonnement de pointe (avec frontières strictes)
    is_reasoning = bool(FLAGSHIP_REASONING_RE.search(m_id))
    if is_reasoning or any(k in m_id for k in ["opus", "sonnet", "405b"]):
        return 5
    if GPT_FLAGSHIP_RE.search(m_id):
        return 5

    # Priorité 4 : Modèles 70B+, MoE lourds (>=35B cumulés) et codeurs spécialisés
    if any(k in m_id for k in ["mistral-large", "deepseek-v3", "codestral", "command-r+"]):
        return 4
    if parameter_sizes and max(parameter_sizes) >= 35:
        return 4

    # Priorité 3 : Modèles rapides intermédiaires (8B à 34B, flash, haiku)
    if any(k in m_id for k in ["flash", "haiku", "mistral-small"]) or any(7.5 < size < 35 for size in parameter_sizes):
        return 3

    # Fallback heuristique basé sur le coût par million de tokens d'entrée
    if prompt_cost_per_m >= 2.0:
        return 5
    elif prompt_cost_per_m >= 0.5:
        return 4
    elif prompt_cost_per_m >= 0.05:
        return 3
    elif prompt_cost_per_m > 0:
        return 2
    else:
        return 3


def parse_openrouter_model(raw: dict[str, Any]) -> Optional[Model]:
    """Convertit un objet modèle brut d'OpenRouter vers la dataclass Model.

    Retourne None si le modèle est invalide (ex: prix négatifs, structure corrompue).
    """
    if not isinstance(raw, dict):
        return None

    model_id = raw.get("id")
    if not model_id or not isinstance(model_id, str):
        return None

    architecture = raw.get("architecture")
    output_modalities = raw.get("output_modalities")
    if is_non_llm_model(
        model_id,
        architecture=architecture if isinstance(architecture, dict) else None,
        output_modalities=output_modalities if isinstance(output_modalities, list) else None,
    ):
        return None

    # Extraction du fournisseur (préfixe avant le '/')
    provider = model_id.split("/")[0] if "/" in model_id else "openrouter"

    pricing = raw.get("pricing")
    if not isinstance(pricing, dict):
        return None

    prompt_val = pricing.get("prompt")
    completion_val = pricing.get("completion")
    if prompt_val is None or completion_val is None:
        return None

    try:
        raw_prompt = float(prompt_val)
        raw_completion = float(completion_val)
    except (TypeError, ValueError):
        return None

    # Filtrer les tarifs non finis (NaN, Inf) et négatifs (tests / placeholders OpenRouter)
    if not (math.isfinite(raw_prompt) and math.isfinite(raw_completion)):
        return None
    if raw_prompt < 0 or raw_completion < 0:
        return None

    cost_in = round(raw_prompt * 1_000_000, 4)
    cost_out = round(raw_completion * 1_000_000, 4)

    is_free = ":free" in model_id or (cost_in == 0.0 and cost_out == 0.0)
    tier = "free_tier" if is_free else "pay_as_you_go"

    try:
        raw_ctx = raw.get("context_length")
        context_window = int(raw_ctx) if raw_ctx is not None else 4096
    except (TypeError, ValueError):
        context_window = 4096

    if context_window < 1:
        context_window = 4096

    supported_params = raw.get("supported_parameters", [])
    if not isinstance(supported_params, list):
        supported_params = []
    supports_tools = "tools" in supported_params or "tool_choice" in supported_params

    # Détection de la vision (multimodalité)
    architecture = raw.get("architecture")
    modality = ""
    arch_input_modalities: list[str] = []
    if isinstance(architecture, dict):
        modality = str(architecture.get("modality", "")).lower()
        aim = architecture.get("input_modalities")
        if isinstance(aim, list):
            arch_input_modalities = [str(x).lower() for x in aim]
    input_modalities = raw.get("input_modalities", [])
    if not isinstance(input_modalities, list):
        input_modalities = []
    all_input_modalities = set(arch_input_modalities + [str(x).lower() for x in input_modalities])
    has_image_input = "image" in all_input_modalities or "image" in modality
    model_id_lower = model_id.lower()
    vision_keywords = (
        "-vl", "-vision", "vision-", "/vision", "omni",
        "gpt-4", "gpt-5", "gpt-6", "gemini-", "claude-",
        "openai/o1", "openai/o3", "openai/o4"
    )
    supports_vision = has_image_input or any(kw in model_id_lower for kw in vision_keywords)

    # Détection des modèles de raisonnement (reasoning / thinking models)
    reasoning_obj = raw.get("reasoning")
    has_reasoning_field = reasoning_obj is not None and reasoning_obj is not False
    reasoning_keywords = ("o1", "o3", "o4", "r1", "qwq", "thinking", "reasoning", "reasoner")
    is_reasoning_id = any(
        re.search(rf"(?:^|[-_/:])({re.escape(kw)})(?:$|[-_/:])", model_id_lower)
        for kw in reasoning_keywords
    )
    supports_reasoning = has_reasoning_field or is_reasoning_id or "reasoning" in supported_params

    complexity_score = estimate_complexity_score(model_id, cost_in)

    try:
        return Model(
            id=model_id,
            provider=provider,
            tier=tier,
            cost_input_per_m=cost_in,
            cost_output_per_m=cost_out,
            context_window=context_window,
            supports_tools=supports_tools,
            complexity_score=complexity_score,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
        )
    except ValueError:
        return None


def write_json_atomic(path: Path, data: object) -> None:
    """Écrit un document JSON via un fichier temporaire puis un remplacement atomique."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        # mkstemp crée par défaut un fichier en 0o600 ; on rétablit les permissions de lecture standard (0o644)
        try:
            os.chmod(temporary_path, 0o644)
        except OSError:
            pass
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def prune_timestamped_backups(
    backup_dir: Path,
    stem: str,
    suffix: str,
    keep: int = MAX_TIMESTAMPED_BACKUPS,
) -> None:
    """Conserve uniquement les sauvegardes horodatées les plus récentes."""
    if keep < 1 or not backup_dir.is_dir():
        return
    archived = sorted(
        path for path in backup_dir.glob(f"{stem}_*{suffix}") if path.is_file()
    )
    excess = len(archived) - keep
    if excess <= 0:
        return
    for obsolete in archived[:excess]:
        obsolete.unlink(missing_ok=True)


def create_backup(
    target_file: Path,
    keep: int = MAX_TIMESTAMPED_BACKUPS,
) -> Tuple[Optional[Path], Optional[Path]]:
    """Crée une sauvegarde horodatée et un fichier .bak si le fichier cible existe.

    Returns:
        Tuple (chemin_backup_horodate, chemin_backup_bak) ou (None, None).
    """
    if not target_file.exists():
        return None, None

    backup_dir = target_file.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    timestamped_backup = backup_dir / f"{target_file.stem}_{timestamp}{target_file.suffix}"
    latest_bak = target_file.with_suffix(target_file.suffix + ".bak")

    shutil.copy2(target_file, timestamped_backup)
    shutil.copy2(target_file, latest_bak)
    prune_timestamped_backups(backup_dir, target_file.stem, target_file.suffix, keep)

    return timestamped_backup, latest_bak


def fetch_openrouter_models(
    timeout: int = 10,
    max_bytes: int = 20_000_000,
    max_retries: int = 3,
    base_backoff_seconds: float = 0.5,
) -> List[dict[str, Any]]:
    """Interroge l'API publique OpenRouter pour récupérer la liste des modèles avec réessai exponentiel."""
    request = urllib.request.Request(
        OPENROUTER_API_URL,
        headers={"User-Agent": "OpenCode-ModelPool/1.0", "Accept": "application/json"},
    )

    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read(max_bytes + 1)
                if len(content) > max_bytes:
                    raise ValueError(f"Réponse OpenRouter trop volumineuse (> {max_bytes} octets).")
                payload: object = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Réponse OpenRouter invalide : liste 'data' absente.")
            models: list[dict[str, Any]] = []
            for raw_model in payload["data"]:
                if isinstance(raw_model, dict):
                    models.append(raw_model)
            return models
        except urllib.error.HTTPError as error:
            last_error = error
            # Rejeu uniquement sur 429 (Too Many Requests) et erreurs serveur 5xx
            if error.code in {429, 500, 502, 503, 504} and attempt < max_retries:
                retry_after_header = error.headers.get("Retry-After") if error.headers else None
                sleep_duration = base_backoff_seconds * (2 ** attempt)
                if retry_after_header:
                    try:
                        sleep_duration = max(float(retry_after_header), 0.05)
                    except ValueError:
                        pass
                time.sleep(sleep_duration)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            if attempt < max_retries:
                sleep_duration = base_backoff_seconds * (2 ** attempt)
                time.sleep(sleep_duration)
                continue
            raise

    if last_error:
        raise last_error
    return []


def sync_models_from_openrouter(
    output_path: Path,
    create_backup_file: bool = True,
    exclude_batch: bool = True,
    min_models_threshold: int = 10,
    raw_models: Optional[List[dict[str, Any]]] = None,
) -> Tuple[int, Optional[Path]]:
    """Télécharge les modèles d'OpenRouter, met à jour le fichier JSON et gère le backup.

    Args:
        output_path: Chemin du fichier JSON de destination (ex: data/models.json).
        create_backup_file: Indique s'il faut sauvegarder l'ancienne version.
        exclude_batch: Exclut les variantes ':batch' d'OpenRouter pour alléger le registre.
        min_models_threshold: Seuil minimal de modèles requis pour écraser le catalogue existant.
        raw_models: Liste brute pré-téléchargée de modèles OpenRouter (optionnel).

    Returns:
        Tuple contenant (nombre_de_modèles_enregistrés, chemin_de_la_sauvegarde).
    """
    if raw_models is None:
        raw_models = fetch_openrouter_models()

    parsed_models: List[Model] = []
    for raw in raw_models:
        model = parse_openrouter_model(raw)
        if not model:
            continue
        if exclude_batch and ":batch" in model.id:
            continue
        parsed_models.append(model)

    if len(parsed_models) < min_models_threshold:
        raise ValueError(
            f"Catalogue OpenRouter anormalement réduit ({len(parsed_models)} modèles < seuil {min_models_threshold}). "
            f"Écriture annulée pour préserver l'intégrité du catalogue local."
        )

    # Création du backup si le fichier existe déjà
    backup_path: Optional[Path] = None
    if create_backup_file and output_path.exists():
        backup_path, _ = create_backup(output_path)

    # Préparation des données JSON
    output_data = {
        "version": "1.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": OPENROUTER_API_URL,
        "total_models": len(parsed_models),
        "models": [
            {
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
            for m in parsed_models
        ],
    }

    write_json_atomic(output_path, output_data)

    return len(parsed_models), backup_path


def sync_models_from_all_providers(
    output_path: Path,
    create_backup_file: bool = True,
    exclude_batch: bool = True,
    min_models_threshold: int = 1,
    include_openrouter: bool = True,
    include_ollama: bool = True,
    ollama_base_url: str = "http://localhost:11434",
    project_dir: Optional[Path] = None,
    opencode_auth_path: Optional[Path] = None,
) -> Tuple[int, Optional[Path], Dict[str, int]]:
    """Synchronise les modèles depuis tous les fournisseurs configurés et détectés.

    Interroge :
    1. OpenRouter (catalogue public étendu)
    2. Ollama local (si joignable via ollama_base_url)
    3. Les fournisseurs directs dont les clés d'API sont disponibles (Mistral, Groq, Google, Anthropic, Cerebras).

    Returns:
        Tuple (total_modèles_enregistrés, chemin_backup, dictionnaire_comptes_par_fournisseur).
    """
    from src.providers.detector import detect_provider_credentials
    from src.providers.ollama import get_ollama_models

    credentials = detect_provider_credentials(
        project_dir=project_dir,
        check_ollama=include_ollama,
        ollama_base_url=ollama_base_url,
        opencode_auth_path=opencode_auth_path,
    )

    models_by_id: Dict[str, Model] = {}
    counts: Dict[str, int] = {}

    # 1. OpenRouter
    if include_openrouter:
        try:
            raw_or = fetch_openrouter_models()
            or_count = 0
            for raw in raw_or:
                m = parse_openrouter_model(raw)
                if not m:
                    continue
                if exclude_batch and ":batch" in m.id:
                    continue
                models_by_id[m.id] = m
                or_count += 1
            counts["openrouter"] = or_count
        except Exception:
            counts["openrouter"] = 0

    # 2. Ollama local
    if include_ollama and credentials.get("ollama") and credentials["ollama"].is_available:
        try:
            ollama_models = get_ollama_models(base_url=ollama_base_url)
            for m in ollama_models:
                models_by_id[m.id] = m
            counts["ollama"] = len(ollama_models)
        except Exception:
            counts["ollama"] = 0

    # 3. Fournisseurs directs si clés présentes
    # Les entrées déjà connues du catalogue de référence (OpenRouter) ne sont pas écrasées :
    # seules les métadonnées OpenRouter font foi pour la notation et la tarification.
    from src.providers.detector import get_provider_api_key
    from src.providers.direct import DIRECT_FETCHERS

    for prov_name, fetcher_fn in DIRECT_FETCHERS.items():
        cred = credentials.get(prov_name)
        if cred and cred.is_available:
            try:
                api_key = get_provider_api_key(
                    prov_name,
                    project_dir=project_dir,
                    opencode_auth_path=opencode_auth_path,
                )
                prov_models = fetcher_fn(api_key=api_key)
                for m in prov_models:
                    models_by_id.setdefault(m.id, m)
                counts[prov_name] = len(prov_models)
            except Exception:
                counts[prov_name] = 0

    all_models = list(models_by_id.values())

    if len(all_models) < min_models_threshold:
        raise ValueError(
            f"Catalogue consolidé anormalement réduit ({len(all_models)} modèles < seuil {min_models_threshold}). "
            f"Écriture annulée pour préserver l'intégrité du catalogue local."
        )

    # Création du backup si le fichier existe
    backup_path: Optional[Path] = None
    if create_backup_file and output_path.exists():
        backup_path, _ = create_backup(output_path)

    output_data = {
        "version": "1.0",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "source": "multi-provider (OpenRouter, Ollama, Direct APIs)",
        "sources_summary": counts,
        "total_models": len(all_models),
        "models": [
            {
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
            for m in all_models
        ],
    }

    write_json_atomic(output_path, output_data)

    return len(all_models), backup_path, counts


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    target = base_dir / "data" / "models.json"
    print(f"🔄 Synchronisation multi-fournisseurs vers {target}...")
    try:
        count, bkp, counts = sync_models_from_all_providers(target, project_dir=base_dir)
        print(f"✅ {count} modèles synchronisés avec succès dans {target} : {counts}")
        if bkp:
            print(f"💾 Sauvegarde précédente conservée : {bkp}")
    except Exception as err:
        print(f"❌ Erreur lors de la synchronisation : {err}")
