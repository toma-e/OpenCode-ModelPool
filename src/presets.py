"""Presets de rôles d'agents prédéfinis pour OpenCode.

Fournit une bibliothèque de profils types d'agents prêts à l'emploi
(codeur expert, relecteur, explorateur rapide, rédacteur de documentation, etc.)
sans effet de bord ni I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.selector import AgentRequirement


@dataclass(frozen=True)
class AgentPreset:
    """Modèle prédéfini de configuration d'un agent pour OpenCode."""

    preset_id: str
    label: str
    description: str
    min_complexity: int
    max_complexity: int
    requires_tools: bool
    prefer_free: bool
    allow_free: bool
    sort_strategy: str
    requires_vision: bool
    requires_reasoning: bool
    prefer_tier1: bool
    reliability_preference: str
    mode: str
    min_context_window: Optional[int] = None
    estimated_tokens_input: int = 500000
    estimated_tokens_output: int = 100000
    max_monthly_budget: Optional[float] = None

    def to_agent_dict(self, custom_name: Optional[str] = None) -> Dict[str, Any]:
        """Convertit le preset en dictionnaire conforme au schéma des exigences d'agents."""
        name = custom_name.strip() if custom_name and custom_name.strip() else self.preset_id
        res: Dict[str, Any] = {
            "name": name,
            "description": self.description,
            "min_complexity": self.min_complexity,
            "max_complexity": self.max_complexity,
            "requires_tools": self.requires_tools,
            "prefer_free": self.prefer_free,
            "allow_free": self.allow_free,
            "sort_strategy": self.sort_strategy,
            "requires_vision": self.requires_vision,
            "requires_reasoning": self.requires_reasoning,
            "prefer_tier1": self.prefer_tier1,
            "reliability_preference": self.reliability_preference,
            "mode": self.mode,
            "estimated_tokens_input": self.estimated_tokens_input,
            "estimated_tokens_output": self.estimated_tokens_output,
        }
        if self.min_context_window is not None:
            res["min_context_window"] = self.min_context_window
        if self.max_monthly_budget is not None:
            res["max_monthly_budget"] = self.max_monthly_budget
        return res


BUILTIN_PRESETS: Dict[str, AgentPreset] = {
    "coder_heavy": AgentPreset(
        preset_id="coder_heavy",
        label="Codeur Expert",
        description="Agent de développement intensif : algorithmes complexes, refactoring lourd et raisonnement poussé.",
        min_complexity=4,
        max_complexity=5,
        requires_tools=True,
        prefer_free=False,
        allow_free=True,
        sort_strategy="lowest_cost",
        requires_vision=False,
        requires_reasoning=True,
        prefer_tier1=True,
        reliability_preference="prefer_stability",
        mode="primary",
        min_context_window=64000,
        estimated_tokens_input=1500000,
        estimated_tokens_output=500000,
        max_monthly_budget=15.0,
    ),
    "code_reviewer": AgentPreset(
        preset_id="code_reviewer",
        label="Relecteur de Code & Sécurité",
        description="Sous-agent d'analyse de diffs et audit de qualité/sécurité en lecture seule avec large fenêtre de contexte.",
        min_complexity=4,
        max_complexity=5,
        requires_tools=False,
        prefer_free=False,
        allow_free=True,
        sort_strategy="lowest_cost",
        requires_vision=False,
        requires_reasoning=True,
        prefer_tier1=True,
        reliability_preference="prefer_stability",
        mode="subagent",
        min_context_window=64000,
        estimated_tokens_input=800000,
        estimated_tokens_output=200000,
        max_monthly_budget=8.0,
    ),
    "fast_researcher": AgentPreset(
        preset_id="fast_researcher",
        label="Explorateur & Recherche Rapide",
        description="Sous-agent ultra-rapide pour exploration de base de code et recherche d'informations en priorité gratuit.",
        min_complexity=2,
        max_complexity=3,
        requires_tools=True,
        prefer_free=True,
        allow_free=True,
        sort_strategy="lowest_cost",
        requires_vision=False,
        requires_reasoning=False,
        prefer_tier1=False,
        reliability_preference="prefer_free",
        mode="subagent",
        min_context_window=32000,
        estimated_tokens_input=500000,
        estimated_tokens_output=100000,
        max_monthly_budget=2.0,
    ),
    "doc_writer": AgentPreset(
        preset_id="doc_writer",
        label="Rédacteur de Documentation",
        description="Sous-agent spécialisé dans la rédaction de docstrings, tutoriels et spécifications claires.",
        min_complexity=3,
        max_complexity=4,
        requires_tools=False,
        prefer_free=False,
        allow_free=True,
        sort_strategy="lowest_cost",
        requires_vision=False,
        requires_reasoning=False,
        prefer_tier1=True,
        reliability_preference="balanced",
        mode="subagent",
        min_context_window=32000,
        estimated_tokens_input=600000,
        estimated_tokens_output=200000,
        max_monthly_budget=5.0,
    ),
    "test_runner": AgentPreset(
        preset_id="test_runner",
        label="Exécuteur de Tests & QA",
        description="Sous-agent automatisant la génération de tests unitaires, l'exécution et le diagnostic d'échecs.",
        min_complexity=3,
        max_complexity=4,
        requires_tools=True,
        prefer_free=False,
        allow_free=True,
        sort_strategy="lowest_cost",
        requires_vision=False,
        requires_reasoning=False,
        prefer_tier1=True,
        reliability_preference="balanced",
        mode="subagent",
        min_context_window=32000,
        estimated_tokens_input=700000,
        estimated_tokens_output=200000,
        max_monthly_budget=5.0,
    ),
}


def get_available_presets() -> Dict[str, AgentPreset]:
    """Retourne l'ensemble des profils prédéfinis d'agents."""
    return dict(BUILTIN_PRESETS)


def create_agent_from_preset(preset_id: str, custom_name: Optional[str] = None) -> Dict[str, Any]:
    """Instancie un dictionnaire de configuration d'agent à partir d'un preset.

    Raises:
        KeyError: Si preset_id n'est pas reconnu.
    """
    preset = BUILTIN_PRESETS.get(preset_id)
    if preset is None:
        valid_keys = ", ".join(sorted(BUILTIN_PRESETS.keys()))
        raise KeyError(f"Preset '{preset_id}' inconnu. Presets disponibles : {valid_keys}")

    agent_dict = preset.to_agent_dict(custom_name=custom_name)
    # Valider avec AgentRequirement
    AgentRequirement.from_dict(agent_dict, f"preset '{preset_id}'")
    return agent_dict
