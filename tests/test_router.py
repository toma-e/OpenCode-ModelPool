"""Tests unitaires pour le routeur multi-fournisseurs et la résolution de priorités."""

from __future__ import annotations

import unittest

from src.providers.detector import ProviderCredentials
from src.providers.router import (
    DEFAULT_PROVIDER_PRIORITY,
    ExecutionTarget,
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


if __name__ == "__main__":
    unittest.main()
