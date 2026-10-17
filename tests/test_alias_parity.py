"""Empirical verification test for backward compatibility alias parity.

Verifies that importing and calling build_modelscope_report_data produces
the exact same result as build_modelpool_report_data under all conditions.
"""

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.exporter import (
    build_modelpool_report_data,
    build_modelscope_report_data,
)
from src.selector import (
    AgentRequirement,
    Model,
    SelectionResult,
)


class TestAliasParity(unittest.TestCase):
    def setUp(self) -> None:
        self.model_fast = Model(
            id="test/model-fast",
            provider="test-provider",
            tier="free_tier",
            cost_input_per_m=0.0,
            cost_output_per_m=0.0,
            context_window=32000,
            supports_tools=True,
            complexity_score=2,
        )
        self.model_fallback = Model(
            id="test/model-fallback",
            provider="test-provider",
            tier="pay_as_you_go",
            cost_input_per_m=1.0,
            cost_output_per_m=2.0,
            context_window=64000,
            supports_tools=True,
            complexity_score=4,
        )
        self.agent_req1 = AgentRequirement(
            name="coder",
            description="Agent de code",
            min_complexity=2,
            max_complexity=3,
            requires_tools=True,
            prefer_free=True,
        )
        self.agent_req2 = AgentRequirement(
            name="planner",
            description="Agent de planification",
            min_complexity=3,
            max_complexity=4,
            requires_tools=True,
            prefer_free=False,
        )
        self.agent_req3 = AgentRequirement(
            name="explorer",
            description="Agent explorateur",
            min_complexity=5,
            max_complexity=5,
            requires_tools=True,
            prefer_free=True,
        )

        self.assigned_result = SelectionResult(
            agent_name="coder",
            model=self.model_fast,
            is_fallback=False,
            candidates=[self.model_fast],
            reason="Correspondance exacte.",
        )
        self.fallback_result = SelectionResult(
            agent_name="planner",
            model=self.model_fallback,
            is_fallback=True,
            candidates=[self.model_fallback],
            reason="Surclassement nécessaire.",
        )
        self.unassigned_result = SelectionResult(
            agent_name="explorer",
            model=None,
            is_fallback=False,
            candidates=[],
            reason="Aucun modèle compatible.",
        )

    def test_alias_identity(self) -> None:
        """Verify that build_modelscope_report_data is an exact reference to build_modelpool_report_data."""
        self.assertIs(
            build_modelscope_report_data,
            build_modelpool_report_data,
            "build_modelscope_report_data must be an alias of build_modelpool_report_data",
        )

    def test_empty_results_parity(self) -> None:
        """Verify identical results with empty inputs when timestamp is fixed."""
        fixed_dt = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
        with patch("src.exporter.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            res_pool = build_modelpool_report_data([], [])
            res_scope = build_modelscope_report_data([], [])

        self.assertEqual(res_pool, res_scope)
        self.assertEqual(res_scope["metadata"]["generator"], "OpenCode-ModelPool")
        self.assertEqual(res_scope["metadata"]["total_agents"], 0)
        self.assertEqual(res_scope["metadata"]["assigned_agents"], 0)
        self.assertEqual(res_scope["metadata"]["unassigned_agents"], 0)

    def test_multi_agent_heterogeneous_parity(self) -> None:
        """Verify identical results with mixed assigned, fallback, and unassigned agents."""
        results = [self.assigned_result, self.fallback_result, self.unassigned_result]
        agents = [self.agent_req1, self.agent_req2, self.agent_req3]

        fixed_dt = datetime(2026, 10, 17, 15, 30, 45, tzinfo=timezone.utc)
        with patch("src.exporter.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            res_pool = build_modelpool_report_data(results, agents)
            res_scope = build_modelscope_report_data(results, agents)

        self.assertEqual(res_pool, res_scope)
        self.assertEqual(res_scope["metadata"]["generator"], "OpenCode-ModelPool")
        self.assertEqual(res_scope["metadata"]["total_agents"], 3)
        self.assertEqual(res_scope["metadata"]["assigned_agents"], 2)
        self.assertEqual(res_scope["metadata"]["unassigned_agents"], 1)

        # Deep assertions on structure
        self.assertIn("agents", res_scope)
        self.assertIn("coder", res_scope["agents"])
        self.assertIn("planner", res_scope["agents"])
        self.assertIn("explorer", res_scope["agents"])

        self.assertEqual(res_scope["agents"]["coder"]["selection_status"], "exact")
        self.assertEqual(res_scope["agents"]["planner"]["selection_status"], "fallback")
        self.assertEqual(res_scope["agents"]["explorer"]["selection_status"], "unassigned")

    def test_identical_exception_behavior(self) -> None:
        """Verify that both functions raise the identical exception when given invalid inputs."""
        with self.assertRaises(TypeError):
            build_modelpool_report_data(None, None)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            build_modelscope_report_data(None, None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
