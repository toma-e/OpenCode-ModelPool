"""Tests unitaires pour le module selector."""

import unittest

from src.selector import (
    AgentRequirement,
    Model,
    is_model_compatible,
    rank_models_for_agent,
    resolve_model_for_agent,
    select_model_for_agent,
)


class TestSelector(unittest.TestCase):
    def setUp(self) -> None:
        self.llama_1b = Model(
            id="meta-llama/llama-3.2-1b-instruct",
            provider="meta",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=8192,
            supports_tools=False,
            complexity_score=1,
            supports_vision=False,
            supports_reasoning=False,
        )
        self.gemini_lite = Model(
            id="google/gemini-2.5-flash-lite",
            provider="google",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=1000000,
            supports_tools=True,
            complexity_score=2,
            supports_vision=True,
            supports_reasoning=False,
        )
        self.gpt_4o_mini = Model(
            id="openai/gpt-4o-mini",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=0.15,
            cost_output_per_m=0.60,
            context_window=128000,
            supports_tools=True,
            complexity_score=2,
            supports_vision=True,
            supports_reasoning=False,
        )
        self.gemini_flash = Model(
            id="google/gemini-2.5-flash",
            provider="google",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=1000000,
            supports_tools=True,
            complexity_score=3,
            supports_vision=True,
            supports_reasoning=False,
        )
        self.llama_70b = Model(
            id="meta-llama/llama-3.3-70b-instruct",
            provider="meta",
            tier="pay_as_you_go",
            cost_input_per_m=0.12,
            cost_output_per_m=0.30,
            context_window=128000,
            supports_tools=True,
            complexity_score=4,
            supports_vision=False,
            supports_reasoning=False,
        )
        self.deepseek_r1 = Model(
            id="deepseek/deepseek-r1",
            provider="deepseek",
            tier="pay_as_you_go",
            cost_input_per_m=0.55,
            cost_output_per_m=2.19,
            context_window=128000,
            supports_tools=True,
            complexity_score=5,
            supports_vision=False,
            supports_reasoning=True,
        )
        self.claude_sonnet = Model(
            id="anthropic/claude-3-5-sonnet",
            provider="anthropic",
            tier="pay_as_you_go",
            cost_input_per_m=3.0,
            cost_output_per_m=15.0,
            context_window=200000,
            supports_tools=True,
            complexity_score=5,
            supports_vision=True,
            supports_reasoning=False,
        )
        self.models = [
            self.llama_1b,
            self.gemini_lite,
            self.gpt_4o_mini,
            self.gemini_flash,
            self.llama_70b,
            self.deepseek_r1,
            self.claude_sonnet,
        ]

    def test_compatibility_tool_support(self) -> None:
        req = AgentRequirement(
            name="coder",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
        )
        self.assertFalse(is_model_compatible(self.llama_1b, req))
        self.assertTrue(is_model_compatible(self.gemini_lite, req))

    def test_doc_agent_selection(self) -> None:
        """doc_agent (complexité 1-2, prefer_free) doit choisir gemini-2.5-flash-lite."""
        req = AgentRequirement(
            name="doc_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=True,
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "google/gemini-2.5-flash-lite")

    def test_coder_agent_selection(self) -> None:
        """coder_agent (complexité 3-4, requires_tools, prefer_free) doit choisir gemini-flash."""
        req = AgentRequirement(
            name="coder_agent",
            description="",
            min_complexity=3,
            max_complexity=4,
            requires_tools=True,
            prefer_free=True,
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "google/gemini-2.5-flash")

    def test_fallback_when_no_exact_match(self) -> None:
        """Si aucun modèle ne satisfait la plage stricte, le fallback surclasse vers le modèle économique."""
        req = AgentRequirement(
            name="strict_agent",
            description="",
            min_complexity=1,
            max_complexity=1,
            requires_tools=True,
            prefer_free=True,
        )
        # Sans fallback -> None
        result_no_fallback = resolve_model_for_agent(req, self.models, allow_fallback=False)
        self.assertIsNone(result_no_fallback.model)
        self.assertFalse(result_no_fallback.is_fallback)

        # Avec fallback -> surclassement vers gemini_lite (score 2, free, tools=True)
        result_fallback = resolve_model_for_agent(req, self.models, allow_fallback=True)
        self.assertIsNotNone(result_fallback.model)
        self.assertTrue(result_fallback.is_fallback)
        self.assertEqual(result_fallback.model.id, "google/gemini-2.5-flash-lite")

    def test_architect_agent_selection(self) -> None:
        """architect_agent (complexité 5, requires_vision) doit choisir claude-3-5-sonnet."""
        req = AgentRequirement(
            name="architect_agent",
            description="",
            min_complexity=5,
            max_complexity=5,
            requires_tools=True,
            prefer_free=False,
            requires_vision=True,
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "anthropic/claude-3-5-sonnet")

    def test_min_context_window_filter(self) -> None:
        """Exclut les modèles ayant une fenêtre de contexte inférieure au seuil."""
        # Pour une complexité 2, gemini_lite a 1M et gpt_4o_mini a 128k
        req = AgentRequirement(
            name="big_doc_agent",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            min_context_window=500000,
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "google/gemini-2.5-flash-lite")

    def test_allowed_providers_filter(self) -> None:
        """Ne retient que les modèles appartenant aux fournisseurs autorisés."""
        req = AgentRequirement(
            name="openai_only_agent",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
            allowed_providers=["openai"],
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "openai/gpt-4o-mini")

    def test_excluded_providers_filter(self) -> None:
        """Exclut explicitement certains fournisseurs."""
        req = AgentRequirement(
            name="no_google_agent",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
            excluded_providers=["google"],
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "openai/gpt-4o-mini")

    def test_force_model_override(self) -> None:
        """Un modèle imposé manuellement doit être sélectionné en priorité absolue."""
        req = AgentRequirement(
            name="forced_agent",
            description="",
            min_complexity=1,
            max_complexity=1,
            requires_tools=False,
            prefer_free=False,
            force_model="anthropic/claude-3-5-sonnet",
        )
        result = resolve_model_for_agent(req, self.models)
        self.assertIsNotNone(result.model)
        self.assertEqual(result.model.id, "anthropic/claude-3-5-sonnet")
        self.assertIn("imposé manuellement", result.reason)

    def test_force_model_not_found(self) -> None:
        """Un modèle imposé inexistant retourne None avec un motif clair."""
        req = AgentRequirement(
            name="forced_unknown_agent",
            description="",
            min_complexity=1,
            max_complexity=1,
            requires_tools=False,
            prefer_free=False,
            force_model="provider/unknown-model",
        )
        result = resolve_model_for_agent(req, self.models)
        self.assertIsNone(result.model)

    def test_force_model_reports_bypassed_constraints(self) -> None:
        req = AgentRequirement(
            name="forced_incompatible",
            description="",
            min_complexity=1,
            max_complexity=1,
            requires_tools=True,
            prefer_free=False,
            min_context_window=100_000,
            allowed_providers=["openai"],
            estimated_tokens_input=2_000_000,
            max_monthly_budget=0.01,
            force_model="meta-llama/llama-3.2-1b-instruct",
        )
        result = resolve_model_for_agent(req, self.models)
        self.assertIsNotNone(result.model)
        self.assertIn("Contraintes contournées", result.reason)
        self.assertIn("support des outils", result.reason)
        self.assertIn("fournisseur non autorisé", result.reason)

    def test_agent_validation_rejects_invalid_values(self) -> None:
        invalid = {
            "name": "bad",
            "min_complexity": 4,
            "max_complexity": 2,
            "requires_tools": "yes",
        }
        with self.assertRaisesRegex(ValueError, "plage de complexité"):
            AgentRequirement.from_dict(invalid, "agent #1")

    def test_agent_validation_rejects_provider_conflict(self) -> None:
        invalid = {
            "name": "bad",
            "min_complexity": 1,
            "max_complexity": 2,
            "requires_tools": False,
            "allowed_providers": ["OpenAI"],
            "excluded_providers": ["openai"],
        }
        with self.assertRaisesRegex(ValueError, "à la fois autorisé et exclu"):
            AgentRequirement.from_dict(invalid)

    def test_model_validation_rejects_negative_cost(self) -> None:
        raw = {
            "id": "test/model",
            "provider": "test",
            "tier": "pay_as_you_go",
            "cost_input_per_m": -1,
            "cost_output_per_m": 0,
            "context_window": 1,
            "supports_tools": True,
            "complexity_score": 1,
        }
        with self.assertRaisesRegex(ValueError, "cost_input_per_m"):
            Model.from_dict(raw)
    def test_max_monthly_budget_filter(self) -> None:
        """Exclut les modèles dont le coût estimé dépasse le budget maximal autorisé."""
        # Pour complexité 2 :
        # gpt_4o_mini coûte in: $0.15/1M, out: $0.60/1M.
        # Avec 2M in et 1M out -> coût = $0.30 + $0.60 = $0.90.
        # Si budget max est $0.50 et prefer_free est False :
        # gpt_4o_mini ($0.90) est rejeté, mais gemini_lite ($0.00) est compatible !
        req = AgentRequirement(
            name="capped_budget_agent",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
            estimated_tokens_input=2_000_000,
            estimated_tokens_output=1_000_000,
            max_monthly_budget=0.50,
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        # Seul gemini_lite respecte le budget max
        self.assertEqual(selected.id, "google/gemini-2.5-flash-lite")


    def test_agent_validation_rejects_invalid_sort_strategy(self) -> None:
        invalid = {
            "name": "bad_strategy",
            "min_complexity": 1,
            "max_complexity": 2,
            "requires_tools": False,
            "sort_strategy": "unknown_strategy",
        }
        with self.assertRaisesRegex(ValueError, "sort_strategy"):
            AgentRequirement.from_dict(invalid)

    def test_sort_strategy_max_performance(self) -> None:
        """max_performance doit préférer le modèle à complexité maximale dans la plage autorisée."""
        # Modèles compatibles pour plage 2 à 4 avec tools:
        # gemini_lite (compl 2, $0), gpt_4o_mini (compl 2, $0.75), gemini_flash (compl 3, $0), llama_70b (compl 4, $0.42)
        # lowest_cost prendrait gemini_flash (compl 3, $0) ou gemini_lite ($0)
        # max_performance avec prefer_free=False doit prendre llama_70b (compl 4)
        req = AgentRequirement(
            name="perf_agent",
            description="",
            min_complexity=2,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="max_performance",
        )
        result = resolve_model_for_agent(req, self.models)
        self.assertIsNotNone(result.model)
        self.assertEqual(result.model.id, "meta-llama/llama-3.3-70b-instruct")
        self.assertEqual(result.model.complexity_score, 4)
        self.assertIn("stratégie: max_performance", result.reason)

    def test_sort_strategy_max_context(self) -> None:
        """max_context doit choisir le modèle offrant la plus grande fenêtre de contexte."""
        # Modèles de complexité 4-5 :
        # llama_70b : context_window = 128_000
        # claude_sonnet : context_window = 200_000
        # Avec lowest_cost : llama_70b est choisi ($0.42 vs $18.0)
        # Avec max_context : claude_sonnet est choisi (200k > 128k)
        req = AgentRequirement(
            name="context_agent",
            description="",
            min_complexity=4,
            max_complexity=5,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="max_context",
        )
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "anthropic/claude-3-5-sonnet")
        self.assertEqual(selected.context_window, 200000)

    def test_sort_strategy_balanced(self) -> None:
        """balanced choisit selon le compromis score qualité/contexte/prix."""
        req = AgentRequirement(
            name="balanced_agent",
            description="",
            min_complexity=2,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="balanced",
        )
        result = resolve_model_for_agent(req, self.models)
        self.assertIsNotNone(result.model)
        self.assertIn("stratégie: balanced", result.reason)

    def test_sort_strategy_fallback_max_performance(self) -> None:
        """En cas de fallback, max_performance sélectionne parmi les modèles au-dessus de max_complexity."""
        # Agent voulant complexité 1 avec tools (aucun en complexité 1 n'a tools: llama_1b n'a pas tools)
        # Les modèles éligibles en fallback sont gemini_lite (2), gpt_4o_mini (2), gemini_flash (3), llama_70b (4), claude_sonnet (5)
        # En max_performance avec prefer_free=False, le modèle le plus puissant claude_sonnet (5) doit être choisi
        req = AgentRequirement(
            name="fallback_agent",
            description="",
            min_complexity=1,
            max_complexity=1,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="max_performance",
        )
        result = resolve_model_for_agent(req, self.models, allow_fallback=True)
        self.assertIsNotNone(result.model)
        self.assertTrue(result.is_fallback)
        self.assertEqual(result.model.id, "deepseek/deepseek-r1")
        self.assertEqual(result.model.complexity_score, 5)
        self.assertIn("stratégie: max_performance", result.reason)


    def test_agent_validation_rejects_prefer_free_when_allow_free_is_false(self) -> None:
        invalid = {
            "name": "contradictory_agent",
            "min_complexity": 1,
            "max_complexity": 2,
            "requires_tools": False,
            "prefer_free": True,
            "allow_free": False,
        }
        with self.assertRaisesRegex(ValueError, "prefer_free.*allow_free"):
            AgentRequirement.from_dict(invalid)

    def test_allow_free_false_excludes_free_models(self) -> None:
        """allow_free=False exclut les modèles gratuits (tier free_tier ou coût 0)."""
        # Complexité 2 avec tools :
        # gemini_lite (free_tier, $0)
        # gpt_4o_mini (pay_as_you_go, $0.75)
        req = AgentRequirement(
            name="paid_only_agent",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
            allow_free=False,
        )
        # gemini_lite doit être incompatible à cause de allow_free=False
        self.assertFalse(is_model_compatible(self.gemini_lite, req))
        self.assertTrue(is_model_compatible(self.gpt_4o_mini, req))

        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "openai/gpt-4o-mini")

    def test_allow_free_false_when_only_free_models_available(self) -> None:
        """Si seuls des modèles gratuits sont disponibles, aucun modèle n'est retenu."""
        # Modèles de complexité 3 avec tools : seulement gemini_flash (free_tier)
        req = AgentRequirement(
            name="strict_paid_agent",
            description="",
            min_complexity=3,
            max_complexity=3,
            requires_tools=True,
            prefer_free=False,
            allow_free=False,
        )
        self.assertFalse(is_model_compatible(self.gemini_flash, req))
        result = resolve_model_for_agent(req, self.models, allow_fallback=False)
        self.assertIsNone(result.model)
    def test_requires_vision_filter(self) -> None:
        """requires_vision=True filtre les modèles sans support vision."""
        # Modèles de complexité 4 avec tools :
        # llama_70b (supports_vision=False)
        # S'il y a un agent qui demande vision en complexité 4, llama_70b est rejeté
        req = AgentRequirement(
            name="vision_agent",
            description="",
            min_complexity=4,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
            requires_vision=True,
        )
        self.assertFalse(is_model_compatible(self.llama_70b, req))
        result = resolve_model_for_agent(req, self.models, allow_fallback=False)
        self.assertIsNone(result.model)
        # Avec fallback vers complexité 5, claude_sonnet supporte la vision !
        result_fb = resolve_model_for_agent(req, self.models, allow_fallback=True)
        self.assertIsNotNone(result_fb.model)
        self.assertEqual(result_fb.model.id, "anthropic/claude-3-5-sonnet")

    def test_requires_reasoning_filter(self) -> None:
        """requires_reasoning=True ne retient que les modèles de réflexion."""
        # En complexité 5 avec tools :
        # deepseek_r1 (supports_reasoning=True)
        # claude_sonnet (supports_reasoning=False)
        req = AgentRequirement(
            name="reasoning_agent",
            description="",
            min_complexity=5,
            max_complexity=5,
            requires_tools=True,
            prefer_free=False,
            requires_reasoning=True,
        )
        self.assertTrue(is_model_compatible(self.deepseek_r1, req))
        self.assertFalse(is_model_compatible(self.claude_sonnet, req))
        selected = select_model_for_agent(req, self.models)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, "deepseek/deepseek-r1")

    def test_prefer_tier1_prioritization(self) -> None:
        """prefer_tier1=True classe les modèles Tier 1 avant les fournisseurs communautaires à score et coût similaires."""
        niche_model = Model(
            id="a-niche-lab/niche-model",
            provider="niche-lab",
            tier="pay_as_you_go",
            cost_input_per_m=0.10,
            cost_output_per_m=0.10,
            context_window=100000,
            supports_tools=True,
            complexity_score=4,
            supports_vision=False,
            supports_reasoning=False,
        )
        tier1_model = Model(
            id="openai/standard-model",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=0.10,
            cost_output_per_m=0.10,
            context_window=100000,
            supports_tools=True,
            complexity_score=4,
            supports_vision=False,
            supports_reasoning=False,
        )
        test_pool = [niche_model, tier1_model]
        req_with_tier1 = AgentRequirement(
            name="dev_agent",
            description="",
            min_complexity=4,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
            prefer_tier1=True,
        )
        selected = select_model_for_agent(req_with_tier1, test_pool)
        self.assertEqual(selected.id, "openai/standard-model")

        req_without_tier1 = AgentRequirement(
            name="dev_agent_cheap",
            description="",
            min_complexity=4,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
            prefer_tier1=False,
        )
        selected_cheap = select_model_for_agent(req_without_tier1, test_pool)
        self.assertEqual(selected_cheap.id, "a-niche-lab/niche-model")

    def test_lowest_cost_prefers_cheaper_community_model_over_expensive_tier1(self) -> None:
        """Sous lowest_cost, un modèle communautaire nettement moins cher prime sur le Tier 1."""
        comm = Model(
            id="community/cheap",
            provider="community",
            tier="pay_as_you_go",
            cost_input_per_m=0.02,
            cost_output_per_m=0.03,
            context_window=32000,
            supports_tools=True,
            complexity_score=3,
        )
        t1 = Model(
            id="openai/costly",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=2.50,
            cost_output_per_m=10.0,
            context_window=32000,
            supports_tools=True,
            complexity_score=3,
        )
        req = AgentRequirement(
            name="test",
            description="",
            min_complexity=3,
            max_complexity=3,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="lowest_cost",
            prefer_tier1=True,
        )
        selected = select_model_for_agent(req, [t1, comm])
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, "community/cheap")

    def test_deterministic_tie_breaker_uses_model_id(self) -> None:
        """En cas d'égalité stricte sur tous les critères, l'ordre alphabétique de model.id départage."""
        m_b = Model(
            id="vendor/model-b",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=1.0,
            cost_output_per_m=1.0,
            context_window=32000,
            supports_tools=True,
            complexity_score=3,
        )
        m_a = Model(
            id="vendor/model-a",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=1.0,
            cost_output_per_m=1.0,
            context_window=32000,
            supports_tools=True,
            complexity_score=3,
        )
        req = AgentRequirement(
            name="test",
            description="",
            min_complexity=3,
            max_complexity=3,
            requires_tools=True,
            prefer_free=False,
            sort_strategy="lowest_cost",
        )
        # Quel que soit l'ordre de passage, model-a doit être classé premier
        ranked_1 = rank_models_for_agent(req, [m_b, m_a])
        ranked_2 = rank_models_for_agent(req, [m_a, m_b])
        self.assertEqual(ranked_1[0].id, "vendor/model-a")
        self.assertEqual(ranked_2[0].id, "vendor/model-a")

    def test_model_from_dict_rejects_nan_pricing(self) -> None:
        """Model.from_dict rejette explicitement les valeurs non finies NaN et Inf."""
        invalid = {
            "id": "vendor/nan-model",
            "provider": "vendor",
            "tier": "pay_as_you_go",
            "cost_input_per_m": float("nan"),
            "cost_output_per_m": 1.0,
            "context_window": 32000,
            "supports_tools": True,
            "complexity_score": 3,
        }
        with self.assertRaisesRegex(ValueError, "nombre fini"):
            Model.from_dict(invalid)

    def test_agent_requirement_accepts_mode_all(self) -> None:
        """AgentRequirement.from_dict accepte le mode 'all' en plus de 'primary' et 'subagent'."""
        data = {
            "name": "omni_agent",
            "description": "Agent multi-mode",
            "min_complexity": 3,
            "max_complexity": 3,
            "requires_tools": True,
            "mode": "all",
        }
        req = AgentRequirement.from_dict(data)
        self.assertEqual(req.mode, "all")

        # Mode non supporté rejeté
        data_invalid = dict(data, mode="unknown_mode")
        with self.assertRaises(ValueError):
            AgentRequirement.from_dict(data_invalid)


if __name__ == "__main__":
    unittest.main()


