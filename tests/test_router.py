"""Tests unitaires pour le routeur multi-fournisseurs et la résolution de priorités."""

from __future__ import annotations

import unittest

from src.providers.detector import ProviderCredentials
from src.providers.router import (
    DEFAULT_PROVIDER_PRIORITY,
    ExecutionTarget,
    match_direct_model_id,
    normalize_model_basename,
    resolve_model_execution_target,
)
from src.selector import Model


class TestRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.ref_qwen = Model(
            id="qwen/qwen-2.5-coder-7b-instruct",
            provider="qwen",
            tier="standard",
            cost_input_per_m=0.2,
            cost_output_per_m=0.4,
            context_window=32768,
            supports_tools=True,
            complexity_score=3,
        )
        self.ref_mistral = Model(
            id="mistralai/mistral-large-2411",
            provider="mistralai",
            tier="flagship",
            cost_input_per_m=2.0,
            cost_output_per_m=6.0,
            context_window=128000,
            supports_tools=True,
            complexity_score=5,
        )
        self.ollama_model = Model(
            id="ollama/qwen2.5-coder:7b",
            provider="ollama",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=32768,
            supports_tools=True,
            complexity_score=3,
        )

    def test_normalize_model_basename(self) -> None:
        self.assertEqual(normalize_model_basename("mistralai/mistral-large-2411"), "mistral-large-2411")
        self.assertEqual(normalize_model_basename("qwen/qwen-2.5-coder-7b-instruct"), "qwen2.5-coder-7b")
        self.assertEqual(normalize_model_basename("ollama/qwen2.5-coder:7b"), "qwen2.5-coder-7b")
        self.assertEqual(normalize_model_basename("google/gemini-2.0-flash-exp:free"), "gemini-2.0-flash-exp")

    def test_priority_routes_to_ollama_when_available(self) -> None:
        creds = {
            "ollama": ProviderCredentials(provider="ollama", is_available=True, source="ollama"),
            "openrouter": ProviderCredentials(provider="openrouter", is_available=True, source="env"),
        }
        priority = ["ollama", "openrouter"]

        target = resolve_model_execution_target(
            reference_model=self.ref_qwen,
            provider_priority=priority,
            credentials=creds,
            ollama_models=[self.ollama_model],
        )

        self.assertEqual(target.channel_provider, "ollama")
        self.assertEqual(target.formatted_model_id, "ollama/qwen2.5-coder:7b")
        self.assertTrue(target.is_local)
        self.assertEqual(target.effective_cost_input_per_m, 0.0)
        self.assertEqual(target.effective_cost_output_per_m, 0.0)

    def test_priority_routes_to_direct_when_direct_before_openrouter(self) -> None:
        creds = {
            "mistralai": ProviderCredentials(provider="mistralai", is_available=True, source="env", masked_key="mis-***"),
            "openrouter": ProviderCredentials(provider="openrouter", is_available=True, source="env", masked_key="sk-***"),
        }
        priority = ["mistralai", "openrouter"]

        target = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=priority,
            credentials=creds,
        )

        self.assertEqual(target.channel_provider, "mistralai")
        self.assertEqual(target.formatted_model_id, "mistral/mistral-large-2411")
        self.assertFalse(target.is_local)
        self.assertEqual(target.effective_cost_input_per_m, 2.0)

    def test_priority_routes_to_openrouter_when_openrouter_comes_first(self) -> None:
        creds = {
            "mistralai": ProviderCredentials(provider="mistralai", is_available=True, source="env", masked_key="mis-***"),
            "openrouter": ProviderCredentials(provider="openrouter", is_available=True, source="env", masked_key="sk-***"),
        }
        priority = ["openrouter", "mistralai"]

        target = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=priority,
            credentials=creds,
        )

        self.assertEqual(target.channel_provider, "openrouter")
        self.assertEqual(target.formatted_model_id, "openrouter/mistralai/mistral-large-2411")
        self.assertFalse(target.is_local)

    def test_execution_target_explicit_offer_metadata(self) -> None:
        """MP-204 : Vérifie que l'ExecutionTarget explicite la provenance des tarifs et le statut."""
        creds = {
            "ollama": ProviderCredentials(provider="ollama", is_available=True, source="ollama"),
            "groq": ProviderCredentials(provider="groq", is_available=True, source="env", masked_key="gsk-***"),
            "openrouter": ProviderCredentials(provider="openrouter", is_available=True, source="env", masked_key="sk-***"),
        }

        # 1. Ollama local
        target_ollama = resolve_model_execution_target(
            reference_model=self.ref_qwen,
            provider_priority=["ollama"],
            credentials=creds,
            ollama_models=[self.ollama_model],
        )
        self.assertEqual(target_ollama.pricing_source, "local_free")
        self.assertEqual(target_ollama.native_model_id, "ollama/qwen2.5-coder:7b")
        self.assertFalse(target_ollama.is_heuristic_match)
        self.assertEqual(target_ollama.verification_status, "verified")

        # 2. API directe avec correspondance vérifiée
        direct_access = {"groq": {"llama-3.3-70b-versatile"}}
        ref_llama = Model(
            id="meta-llama/llama-3.3-70b-instruct", provider="meta-llama", tier="flagship",
            cost_input_per_m=2.0, cost_output_per_m=4.0, context_window=128000,
            supports_tools=True, complexity_score=5,
        )
        target_direct = resolve_model_execution_target(
            reference_model=ref_llama,
            provider_priority=["groq"],
            credentials=creds,
            direct_access=direct_access,
        )
        self.assertEqual(target_direct.channel_provider, "groq")
        self.assertEqual(target_direct.native_model_id, "llama-3.3-70b-versatile")
        self.assertEqual(target_direct.pricing_source, "direct_api_pricing")
        self.assertEqual(target_direct.effective_cost_input_per_m, 0.59)
        self.assertEqual(target_direct.effective_cost_output_per_m, 0.79)
        self.assertFalse(target_direct.is_heuristic_match)
        self.assertEqual(target_direct.verification_status, "verified")

    def test_match_direct_model_id_edge_cases(self) -> None:
        """Vérifie match_direct_model_id pour listes vides, correspondances exactes, colons et normalisation."""
        self.assertIsNone(match_direct_model_id("mistralai/mistral-large-2411", []))
        self.assertIsNone(match_direct_model_id("mistralai/mistral-large-2411", set()))

        # Correspondance exacte insensible à la casse
        available = ["mistral-large-latest", "codestral-latest"]
        self.assertEqual(
            match_direct_model_id("mistralai/mistral-large-latest", available),
            "mistral-large-latest",
        )

        # Correspondance avec élimination du suffixe deux-points (:free, etc.)
        available_google = ["gemini-2.0-flash-exp"]
        self.assertEqual(
            match_direct_model_id("google/gemini-2.0-flash-exp:free", available_google),
            "gemini-2.0-flash-exp",
        )

        # Correspondance canonique si l'ID exact n'est pas présent
        available_qwen = ["qwen2.5-coder-7b-instruct"]
        self.assertEqual(
            match_direct_model_id("qwen/qwen-2.5-coder-7b-instruct", available_qwen),
            "qwen2.5-coder-7b-instruct",
        )

        # Modèle complètement absent
        self.assertIsNone(match_direct_model_id("anthropic/claude-3-5-sonnet-20241022", available))

    def test_resolve_model_execution_target_exclusions(self) -> None:
        """Vérifie la gestion des exclusions par canal (provider:key) et par cible spécifique."""
        creds = {
            "mistralai": ProviderCredentials("mistralai", True, "env", "sk-mis***"),
            "openrouter": ProviderCredentials("openrouter", True, "env", "sk-or***"),
        }

        # Exclusion par provider:key
        t_prov_excl = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=["mistralai", "openrouter"],
            credentials=creds,
            excluded_targets={"provider:mistralai"},
        )
        self.assertEqual(t_prov_excl.channel_provider, "openrouter")

        # Exclusion par ID formaté direct ("mistral/mistral-large-2411")
        t_target_excl = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=["mistralai", "openrouter"],
            credentials=creds,
            excluded_targets={"mistral/mistral-large-2411"},
        )
        self.assertEqual(t_target_excl.channel_provider, "openrouter")

        # Exclusion de l'unique modèle Ollama
        creds_ollama = {"ollama": ProviderCredentials("ollama", True, "ollama")}
        t_ollama_excl = resolve_model_execution_target(
            reference_model=self.ref_qwen,
            provider_priority=["ollama"],
            credentials=creds_ollama,
            ollama_models=[self.ollama_model],
            excluded_targets={"ollama/qwen2.5-coder:7b"},
        )
        self.assertEqual(t_ollama_excl.channel_provider, "qwen")  # Default fallback provider

    def test_resolve_model_execution_target_direct_pricing_sources(self) -> None:
        """Vérifie la résolution des sources de prix directes (reference_model_catalog, free_tier, unknown)."""
        creds = {
            "mistralai": ProviderCredentials("mistralai", True, "env", "sk-mis***"),
            "google": ProviderCredentials("google", True, "env", "sk-goog***"),
        }

        # 1. reference_model_catalog (modèle payant non répertorié dans KNOWN_MODEL_PRICING)
        ref_custom_mistral = Model(
            id="mistralai/custom-mistral-model", provider="mistralai", tier="pay_as_you_go",
            cost_input_per_m=1.5, cost_output_per_m=4.5, context_window=32768,
            supports_tools=True, complexity_score=3,
        )
        t_custom = resolve_model_execution_target(
            reference_model=ref_custom_mistral,
            provider_priority=["mistralai"],
            credentials=creds,
            direct_access={"mistralai": {"custom-mistral-model"}},
        )
        self.assertEqual(t_custom.pricing_source, "reference_model_catalog")
        self.assertEqual(t_custom.effective_cost_input_per_m, 1.5)
        self.assertEqual(t_custom.effective_cost_output_per_m, 4.5)

        # 2. free_tier (modèle tier free)
        ref_free_google = Model(
            id="google/gemini-2.0-flash-exp:free", provider="google", tier="free",
            cost_input_per_m=0.0, cost_output_per_m=0.0, context_window=1048576,
            supports_tools=True, complexity_score=3,
        )
        t_free = resolve_model_execution_target(
            reference_model=ref_free_google,
            provider_priority=["google"],
            credentials=creds,
            direct_access={"google": {"gemini-2.0-flash-exp"}},
        )
        self.assertEqual(t_free.pricing_source, "free_tier")
        self.assertEqual(t_free.effective_cost_input_per_m, 0.0)

        # 3. free_tier (modèle tier pay_as_you_go mais avec coûts 0.0 car is_free est True)
        ref_zero_payg = Model(
            id="google/experimental-model", provider="google", tier="pay_as_you_go",
            cost_input_per_m=0.0, cost_output_per_m=0.0, context_window=32768,
            supports_tools=True, complexity_score=3,
        )
        t_zero = resolve_model_execution_target(
            reference_model=ref_zero_payg,
            provider_priority=["google"],
            credentials=creds,
            direct_access={"google": {"experimental-model"}},
        )
        self.assertEqual(t_zero.pricing_source, "free_tier")

    def test_resolve_model_execution_target_direct_access_miss_fallthrough(self) -> None:
        """Vérifie qu'un échec de correspondance dans direct_access fait passer au fournisseur suivant."""
        creds = {
            "mistralai": ProviderCredentials("mistralai", True, "env", "sk-mis***"),
            "openrouter": ProviderCredentials("openrouter", True, "env", "sk-or***"),
        }
        # direct_access contient uniquement 'mistral-small', alors que le modèle demandé est 'mistral-large-2411'
        direct_access = {"mistralai": {"mistral-small"}}

        target = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=["mistralai", "openrouter"],
            credentials=creds,
            direct_access=direct_access,
        )
        self.assertEqual(target.channel_provider, "openrouter")
        self.assertEqual(target.formatted_model_id, "openrouter/mistralai/mistral-large-2411")

    def test_resolve_model_execution_target_provider_aliases_and_case(self) -> None:
        """Vérifie la prise en compte des alias de fournisseurs (mistral, gemini) et la tolérance aux majuscules."""
        creds = {
            "mistralai": ProviderCredentials("mistralai", True, "env", "sk-mis***"),
            "google": ProviderCredentials("google", True, "env", "sk-goog***"),
        }
        priority = ["MISTRAL", "GEMINI"]

        target = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=priority,
            credentials=creds,
        )
        self.assertEqual(target.channel_provider, "mistralai")

    def test_resolve_model_execution_target_openrouter_prefix_and_unverified(self) -> None:
        """Vérifie la mise en forme du préfixe openrouter/ et le statut unverified sans clé OpenRouter."""
        ref_or_model = Model(
            id="openrouter/anthropic/claude-3-5-sonnet", provider="anthropic", tier="flagship",
            cost_input_per_m=3.0, cost_output_per_m=15.0, context_window=200000,
            supports_tools=True, complexity_score=5,
        )
        # Clé OpenRouter non disponible
        creds: dict[str, ProviderCredentials] = {}

        target = resolve_model_execution_target(
            reference_model=ref_or_model,
            provider_priority=["openrouter"],
            credentials=creds,
        )
        self.assertEqual(target.channel_provider, "openrouter")
        self.assertEqual(target.formatted_model_id, "openrouter/anthropic/claude-3-5-sonnet")
        self.assertEqual(target.verification_status, "unverified")

    def test_resolve_model_execution_target_fallback_defaults(self) -> None:
        """Vérifie le repli par défaut si la liste des priorités est vide ou si aucun canal ne correspond."""
        target_empty = resolve_model_execution_target(
            reference_model=self.ref_mistral,
            provider_priority=[],
            credentials={},
        )
        self.assertEqual(target_empty.channel_provider, "mistralai")
        self.assertEqual(target_empty.formatted_model_id, "openrouter/mistralai/mistral-large-2411")
        self.assertTrue(target_empty.is_heuristic_match)
        self.assertEqual(target_empty.description_label, "Standard")

        # Modèle de référence avec un ID non préfixé
        ref_simple = Model(
            id="some-custom-model", provider="", tier="pay_as_you_go",
            cost_input_per_m=1.0, cost_output_per_m=1.0, context_window=8000,
            supports_tools=False, complexity_score=2,
        )
        target_simple = resolve_model_execution_target(
            reference_model=ref_simple,
            provider_priority=[],
            credentials={},
        )
        self.assertEqual(target_simple.channel_provider, "openrouter")
        self.assertEqual(target_simple.formatted_model_id, "openrouter/some-custom-model")

    def test_canonicalize_and_match_opencode_direct_models(self) -> None:
        """Vérifie la normalisation et la résolution d'alias des modèles directs OpenCode."""
        mistral_available = [
            "codestral-latest",
            "mistral-large-4-0",
            "mistral-large-4",
            "ministral-14b-latest",
        ]
        # mistralai/mistral-large-4-0 doit privilégier mistral-large-4 pour la compatibilité OpenCode
        matched = match_direct_model_id("mistralai/mistral-large-4-0", mistral_available, opencode_prefix="mistral")
        self.assertEqual(matched, "mistral-large-4")

        # ministral-14b-latest doit être canonisé en ministral-14b-2512
        matched_mini = match_direct_model_id("mistralai/ministral-14b-latest", mistral_available, opencode_prefix="mistral")
        self.assertEqual(matched_mini, "ministral-14b-2512")

    def test_resolve_model_execution_target_groq_tpm_constraint(self) -> None:
        """Vérifie qu'un agent exigeant un large contexte (>8k) n'est pas dérouté sur Groq à cause du TPM."""
        from src.selector import AgentRequirement

        ref_gpt_oss = Model(
            id="openai/gpt-oss-120b",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=0.15,
            cost_output_per_m=0.6,
            context_window=131072,
            supports_tools=True,
            complexity_score=4,
        )
        creds = {
            "groq": ProviderCredentials("groq", True, "env", "gsk-***"),
            "openrouter": ProviderCredentials("openrouter", True, "env", "sk-***"),
        }
        direct_access = {"groq": {"openai/gpt-oss-120b"}}

        # Agent build avec un large contexte de 64k tokens
        build_agent = AgentRequirement.from_dict({
            "name": "build",
            "description": "Agent de code",
            "min_complexity": 4,
            "max_complexity": 5,
            "requires_tools": True,
            "min_context_window": 64000,
        })

        # Avec la contrainte d'agent build, Groq doit être ignoré au profit d'OpenRouter
        target_build = resolve_model_execution_target(
            reference_model=ref_gpt_oss,
            provider_priority=["groq", "openrouter"],
            credentials=creds,
            direct_access=direct_access,
            agent_requirement=build_agent,
        )
        self.assertEqual(target_build.channel_provider, "openrouter")
        self.assertEqual(target_build.formatted_model_id, "openrouter/openai/gpt-oss-120b")

        # Petit agent explore avec 4000 tokens de contexte : Groq est autorisé
        explore_agent = AgentRequirement.from_dict({
            "name": "explore",
            "description": "Agent explore",
            "min_complexity": 2,
            "max_complexity": 3,
            "requires_tools": False,
            "min_context_window": 4000,
        })
        target_explore = resolve_model_execution_target(
            reference_model=ref_gpt_oss,
            provider_priority=["groq", "openrouter"],
            credentials=creds,
            direct_access=direct_access,
            agent_requirement=explore_agent,
        )
        self.assertEqual(target_explore.channel_provider, "groq")
        self.assertEqual(target_explore.formatted_model_id, "groq/openai/gpt-oss-120b")


if __name__ == "__main__":
    unittest.main()
