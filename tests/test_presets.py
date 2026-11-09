"""Tests unitaires du module pur src/presets.py."""

from __future__ import annotations

import unittest

from src.presets import create_agent_from_preset, get_available_presets
from src.selector import AgentRequirement


class TestPresets(unittest.TestCase):
    """Vérifie le chargement et la conformité des presets d'agents."""

    def test_builtin_presets_validity(self) -> None:
        presets = get_available_presets()
        self.assertGreaterEqual(len(presets), 5)
        for preset_id, preset in presets.items():
            agent_dict = preset.to_agent_dict()
            self.assertEqual(agent_dict["name"], preset_id)
            req = AgentRequirement.from_dict(agent_dict)
            self.assertEqual(req.name, preset_id)
            self.assertTrue(1 <= req.min_complexity <= req.max_complexity <= 5)

    def test_create_agent_from_preset_with_custom_name(self) -> None:
        agent_dict = create_agent_from_preset("code_reviewer", custom_name="security_auditor")
        self.assertEqual(agent_dict["name"], "security_auditor")
        self.assertEqual(agent_dict["mode"], "subagent")
        self.assertFalse(agent_dict["requires_tools"])
        self.assertEqual(agent_dict["reliability_preference"], "prefer_stability")

    def test_create_agent_from_preset_unknown(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            create_agent_from_preset("non_existent_preset")
        self.assertIn("non_existent_preset", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
