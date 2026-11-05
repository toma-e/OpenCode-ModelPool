"""Tests unitaires du module pur src/presets.py."""

from __future__ import annotations

import unittest

from src.presets import BUILTIN_PRESETS, create_agent_from_preset, get_available_presets
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

    def test_create_agent_from_preset_sanitization_in_service(self) -> None:
        """Vérifie que la couche service applique les restrictions de sécurité sur le nom de l'agent."""
        import tempfile
        from pathlib import Path
        from src.service import ApplicationService
        from tests.test_service import write_valid_workspace

        with tempfile.TemporaryDirectory() as temp_dir:
            ws_path = Path(temp_dir)
            write_valid_workspace(ws_path)
            svc = ApplicationService(ws_path)

            # 1. Nom contenant des balises script
            res = svc.add_agent_from_preset("coder_heavy", custom_name="<script>alert(1)</script>")
            self.assertFalse(res.ok)
            self.assertIn("non autorisés", res.message)

            # 2. Nom vide ou composé d'espaces
            res_empty = svc.add_agent_from_preset("coder_heavy", custom_name="   ")
            self.assertFalse(res_empty.ok)
            self.assertIn("vide", res_empty.message)

            # 3. Nom trop long (> 64 caractères)
            res_long = svc.add_agent_from_preset("coder_heavy", custom_name="a" * 65)
            self.assertFalse(res_long.ok)
            self.assertIn("64 caractères", res_long.message)

            # 4. Nom valide avec caractères autorisés (lettres, chiffres, tirets, underscores, points)
            res_ok = svc.add_agent_from_preset("coder_heavy", custom_name="valid-agent_1.0")
            self.assertTrue(res_ok.ok)
            self.assertIn("valid-agent_1.0", res_ok.message)


if __name__ == "__main__":
    unittest.main()
