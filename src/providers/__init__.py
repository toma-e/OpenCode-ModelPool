"""Sous-package des connecteurs de fournisseurs LLM et détection de clés."""

from src.providers.detector import (
    ProviderCredentials,
    detect_provider_credentials,
    get_available_provider_names,
    is_ollama_reachable,
    mask_key,
)
from src.providers.direct import (
    fetch_anthropic_models,
    fetch_cerebras_models,
    fetch_google_models,
    fetch_groq_models,
    fetch_mistral_models,
)
from src.providers.ollama import (
    fetch_ollama_tags,
    get_ollama_models,
    parse_ollama_model,
)

from src.providers.router import (
    DEFAULT_PROVIDER_PRIORITY,
    DIRECT_CHANNELS,
    ExecutionTarget,
    match_direct_model_id,
    normalize_model_basename,
    resolve_model_execution_target,
)
from src.providers.access import (
    ProviderAccess,
    probe_provider_access,
    read_provider_access,
    resolve_verified_access,
    write_provider_access,
)

__all__ = [
    "DEFAULT_PROVIDER_PRIORITY",
    "DIRECT_CHANNELS",
    "ExecutionTarget",
    "ProviderAccess",
    "ProviderCredentials",
    "detect_provider_credentials",
    "fetch_anthropic_models",
    "fetch_cerebras_models",
    "fetch_google_models",
    "fetch_groq_models",
    "fetch_mistral_models",
    "fetch_ollama_tags",
    "get_available_provider_names",
    "get_ollama_models",
    "is_ollama_reachable",
    "mask_key",
    "match_direct_model_id",
    "normalize_model_basename",
    "parse_ollama_model",
    "probe_provider_access",
    "read_provider_access",
    "resolve_model_execution_target",
    "resolve_verified_access",
    "write_provider_access",
]
