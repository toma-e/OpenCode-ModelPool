"""Tests unitaires pour le module de simulation budgétaire budget.py."""

import unittest

from src.budget import calculate_agent_cost, simulate_agent_budget, simulate_fleet_budget
from src.selector import AgentRequirement, Model, SelectionResult


class TestBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.free_model = Model(
            id="google/gemini-2.5-flash-lite",
            provider="google",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=1000000,
            supports_tools=True,
            complexity_score=2,
        )
        self.paid_model = Model(
            id="openai/gpt-4o-mini",
            provider="openai",
            tier="pay_as_you_go",
            cost_input_per_m=0.15,
            cost_output_per_m=0.60,
            context_window=128000,
            supports_tools=True,
            complexity_score=2,
        )

    def test_calculate_agent_cost(self) -> None:
        # 1M in ($0.15), 500k out (0.5 * $0.60 = $0.30) -> total $0.45
        cin, cout, ctotal = calculate_agent_cost(self.paid_model, 1_000_000, 500_000)
        self.assertEqual(cin, 0.15)
        self.assertEqual(cout, 0.30)
        self.assertEqual(ctotal, 0.45)

    def test_simulate_agent_budget_free(self) -> None:
        req = AgentRequirement(
            name="free_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=True,
            estimated_tokens_input=200_000,
            estimated_tokens_output=50_000,
        )
        report = simulate_agent_budget(req, self.free_model)
        self.assertEqual(report.monthly_total_cost, 0.0)
        self.assertFalse(report.budget_exceeded)
        self.assertIsNone(report.quota_warning)

    def test_simulate_agent_budget_quota_warning(self) -> None:
        # Volume > 1M tokens sur modèle free_tier
        req = AgentRequirement(
            name="heavy_free_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=True,
            estimated_tokens_input=1_200_000,
            estimated_tokens_output=300_000,
        )
        report = simulate_agent_budget(req, self.free_model)
        self.assertIsNotNone(report.quota_warning)
        assert report.quota_warning is not None
        self.assertIn("Risque d'atteinte des limites", report.quota_warning)

    def test_simulate_agent_budget_exceeded(self) -> None:
        # Plafond de $0.20 alors que le coût est de $0.45
        req = AgentRequirement(
            name="budget_capped_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=1_000_000,
            estimated_tokens_output=500_000,
            max_monthly_budget=0.20,
        )
        report = simulate_agent_budget(req, self.paid_model)
        self.assertEqual(report.monthly_total_cost, 0.45)
        self.assertTrue(report.budget_exceeded)

    def test_simulate_fleet_budget(self) -> None:
        req1 = AgentRequirement(
            name="agent1",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=True,
            estimated_tokens_input=500_000,
            estimated_tokens_output=100_000,
        )
        req2 = AgentRequirement(
            name="agent2",
            description="",
            min_complexity=2,
            max_complexity=2,
            requires_tools=True,
            prefer_free=False,
            estimated_tokens_input=1_000_000,
            estimated_tokens_output=500_000,
        )
        res1 = SelectionResult("agent1", self.free_model, False, [self.free_model], "ok")
        res2 = SelectionResult("agent2", self.paid_model, False, [self.paid_model], "ok")

        fleet = simulate_fleet_budget([res1, res2], [req1, req2], reference_paid_cost_per_m=0.50)
        self.assertEqual(fleet.total_monthly_cost, 0.45)
        self.assertEqual(fleet.total_tokens, 2_100_000)
        # 600k tokens gratuits * $0.50/1M = $0.30 d'économies
        self.assertEqual(fleet.free_tier_savings, 0.30)
        self.assertEqual(len(fleet.agent_reports), 2)

    def test_simulate_budget_local_execution_target(self) -> None:
        """Les cibles locales (Ollama) ont un coût API nul et un disclaimer matériel."""
        from src.providers.router import ExecutionTarget
        target = ExecutionTarget(
            channel_provider="ollama",
            formatted_model_id="ollama/qwen2.5-coder:7b",
            effective_cost_input_per_m=0.0,
            effective_cost_output_per_m=0.0,
            is_local=True,
            description_label="Ollama Local",
            access_verified=True,
            pricing_source="local_free",
        )
        req = AgentRequirement("coder", "", 2, 3, True, False, estimated_tokens_input=1_000_000, estimated_tokens_output=500_000)
        report = simulate_agent_budget(req, self.paid_model, execution_target=target)
        self.assertEqual(report.monthly_total_cost, 0.0)
        self.assertTrue(report.is_local)
        self.assertTrue(report.is_estimable)
        self.assertIn("0$ API", report.disclaimer)

    def test_simulate_budget_unknown_pricing(self) -> None:
        """Un modèle sans tarif répertorié est marqué non estimable."""
        from src.providers.router import ExecutionTarget
        target = ExecutionTarget(
            channel_provider="mistral",
            formatted_model_id="mistral/unknown-model",
            effective_cost_input_per_m=0.0,
            effective_cost_output_per_m=0.0,
            is_local=False,
            description_label="Mistral AI",
            access_verified=True,
            pricing_source="unknown",
        )
        req = AgentRequirement("special", "", 2, 3, True, False, estimated_tokens_input=100_000, estimated_tokens_output=50_000)
        report = simulate_agent_budget(req, self.paid_model, execution_target=target)
        self.assertFalse(report.is_estimable)

        # La flotte globale hérite du statut non estimable
        res = SelectionResult("special", self.paid_model, False, [self.paid_model], "ok")
        fleet = simulate_fleet_budget([res], [req], execution_targets=[target])
        self.assertFalse(fleet.is_total_estimable)

        # Cible None dans execution_targets
        fleet_with_none_target = simulate_fleet_budget([res], [req], execution_targets=[None])
        self.assertTrue(fleet_with_none_target.is_total_estimable)

    def test_simulate_agent_budget_no_model(self) -> None:
        """Agent sans modèle attribué (model=None)."""
        req = AgentRequirement(
            name="unassigned_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=150_000,
            estimated_tokens_output=50_000,
            max_monthly_budget=5.0,
        )
        report = simulate_agent_budget(req, None)
        self.assertEqual(report.agent_name, "unassigned_agent")
        self.assertEqual(report.model_id, "aucun")
        self.assertEqual(report.tier, "non_attribué")
        self.assertEqual(report.monthly_input_cost, 0.0)
        self.assertEqual(report.monthly_output_cost, 0.0)
        self.assertEqual(report.monthly_total_cost, 0.0)
        self.assertEqual(report.max_budget, 5.0)
        self.assertFalse(report.budget_exceeded)
        self.assertIn("Aucun modèle attribué", report.quota_warning or "")
        self.assertEqual(report.disclaimer, "Aucun modèle configuré.")

    def test_simulate_agent_budget_zero_cost_payg_not_estimable(self) -> None:
        """Modèle pay-as-you-go avec target sans coût effectif (effective_cost=0) marqué non estimable."""
        from src.providers.router import ExecutionTarget
        target = ExecutionTarget(
            channel_provider="openrouter",
            formatted_model_id="custom/unpriced-payg",
            effective_cost_input_per_m=0.0,
            effective_cost_output_per_m=0.0,
            is_local=False,
            description_label="OpenRouter",
            access_verified=True,
            pricing_source="catalog",
        )
        req = AgentRequirement(
            name="test_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=100_000,
            estimated_tokens_output=50_000,
        )
        report = simulate_agent_budget(req, self.paid_model, execution_target=target)
        self.assertFalse(report.is_estimable)
        self.assertIn("Prévision estimative non contractuelle (tarifs API hors taxes).", report.disclaimer)

    def test_simulate_agent_budget_custom_execution_target_pricing(self) -> None:
        """Cible d'exécution non locale avec tarifs effectifs spécifiques."""
        from src.providers.router import ExecutionTarget
        target = ExecutionTarget(
            channel_provider="google",
            formatted_model_id="google/gemini-2.0-flash",
            effective_cost_input_per_m=0.10,
            effective_cost_output_per_m=0.40,
            is_local=False,
            description_label="Google AI Studio",
            access_verified=True,
            pricing_source="direct_api",
        )
        req = AgentRequirement(
            name="target_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=1_000_000,
            estimated_tokens_output=500_000,
        )
        # 1M tokens in * 0.10 = 0.10, 500k tokens out * 0.40 = 0.20 -> total = 0.30
        report = simulate_agent_budget(req, self.paid_model, execution_target=target)
        self.assertEqual(report.channel_provider, "google")
        self.assertEqual(report.pricing_source, "direct_api")
        self.assertAlmostEqual(report.monthly_input_cost, 0.10)
        self.assertAlmostEqual(report.monthly_output_cost, 0.20)
        self.assertAlmostEqual(report.monthly_total_cost, 0.30)
        self.assertTrue(report.is_estimable)
        self.assertFalse(report.is_local)
        self.assertIn("tarifs API hors taxes", report.disclaimer)

    def test_simulate_agent_budget_threshold_boundaries(self) -> None:
        """Vérifie les conditions limites (frontières) de quota_warning et de budget_exceeded."""
        # Seuil de quota gratuit = 1_000_000 tokens
        # Exactement 1_000_000 tokens: pas d'avertissement de quota
        req_exact = AgentRequirement(
            name="exact_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=True,
            estimated_tokens_input=800_000,
            estimated_tokens_output=200_000,
        )
        report_exact = simulate_agent_budget(req_exact, self.free_model)
        self.assertIsNone(report_exact.quota_warning)

        # 1_000_001 tokens: déclenchement de l'avertissement
        req_over = AgentRequirement(
            name="over_agent",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=True,
            estimated_tokens_input=800_001,
            estimated_tokens_output=200_000,
        )
        report_over = simulate_agent_budget(req_over, self.free_model)
        self.assertIsNotNone(report_over.quota_warning)

        # Frontière de budget: coût exact = 0.45, max_budget = 0.45 -> False
        req_cap_exact = AgentRequirement(
            name="capped_exact",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=1_000_000,
            estimated_tokens_output=500_000,
            max_monthly_budget=0.45,
        )
        report_cap_exact = simulate_agent_budget(req_cap_exact, self.paid_model)
        self.assertEqual(report_cap_exact.monthly_total_cost, 0.45)
        self.assertFalse(report_cap_exact.budget_exceeded)

    def test_fleet_budget_report_warnings_property(self) -> None:
        """Vérifie has_budget_warnings sur FleetBudgetReport."""
        req_normal = AgentRequirement(
            name="normal",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=100_000,
            estimated_tokens_output=50_000,
        )
        res_normal = SelectionResult("normal", self.paid_model, False, [self.paid_model], "ok")
        fleet_ok = simulate_fleet_budget([res_normal], [req_normal])
        self.assertFalse(fleet_ok.has_budget_warnings)

        # Avec un avertissement de budget dépassé
        req_capped = AgentRequirement(
            name="capped",
            description="",
            min_complexity=1,
            max_complexity=2,
            requires_tools=False,
            prefer_free=False,
            estimated_tokens_input=1_000_000,
            estimated_tokens_output=500_000,
            max_monthly_budget=0.10,
        )
        res_capped = SelectionResult("capped", self.paid_model, False, [self.paid_model], "ok")
        fleet_warn = simulate_fleet_budget([res_capped], [req_capped])
        self.assertTrue(fleet_warn.has_budget_warnings)


if __name__ == "__main__":
    unittest.main()
