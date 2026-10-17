import unittest
from unittest import mock

from src.providers import direct
from src.selector import AgentRequirement, Model, resolve_model_for_agent
from src.exporter import build_modelpool_report_data


def _model(model_id: str, cost: float) -> Model:
    return Model(
        id=model_id, provider=model_id.split("/")[0], tier="pay_as_you_go",
        cost_input_per_m=cost, cost_output_per_m=cost, context_window=128000,
        supports_tools=True, complexity_score=4,
    )


class TestChannelPriority(unittest.TestCase):
    def setUp(self):
        self.req = AgentRequirement(
            name="a", description="d", min_complexity=3, max_complexity=5, requires_tools=True,
            prefer_free=False, allow_free=True, sort_strategy="lowest_cost",
        )
        self.free_or = _model("nvidia/free-model:free", 0.0)
        self.google = _model("google/gemini-2.5-flash", 1.0)

    def test_without_rank_cheapest_wins(self):
        res = resolve_model_for_agent(self.req, [self.free_or, self.google])
        self.assertEqual(res.model.id, self.free_or.id)

    def test_channel_rank_prefers_priority_channel(self):
        rank = {self.google.id: 0, self.free_or.id: 1}
        res = resolve_model_for_agent(self.req, [self.free_or, self.google], channel_rank=rank)
        self.assertEqual(res.model.id, self.google.id)
        self.assertEqual(res.candidates[1].id, self.free_or.id)

    def test_http_get_sets_user_agent(self):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["ua"] = req.get_header("User-agent")
            raise OSError("stop")

        with mock.patch.object(direct.urllib.request, "urlopen", fake_urlopen):
            self.assertIsNone(direct._http_get_json("https://x.invalid", {"Accept": "a"}))
        self.assertTrue(captured["ua"].startswith("OpenCode-ModelPool"))

    def test_report_contains_fallback_chain(self):
        res = resolve_model_for_agent(self.req, [self.google])
        data = build_modelpool_report_data([res], [self.req], fallback_chains={"a": ["openrouter/x"]})
        self.assertEqual(data["agents"]["a"]["fallback_chain"], ["openrouter/x"])


if __name__ == "__main__":
    unittest.main()
