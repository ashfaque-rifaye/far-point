import json

import pytest

from myrmidon.escalate import NovaEscalator, render_prompt
from myrmidon.memory import MomentLog
from myrmidon.stats import StatsStore
from patterns.reflex_gate import Rule, ScriptedModel, contains_image

RULES = [Rule(1, "enlarge_text", "Viewing distance says too close.", "ends with 'too close'", "says 'distance OK'"),
         Rule(3, "dark_mode", "Theme line says mismatch.", "says mismatch", "says suits the room")]
STATE = "Measured now:\n- Viewing distance: 29 cm, closer than 30 cm for 6 s (limit 5 s): too close.\n- Activity: idle."


class Clock:
    def __init__(self):
        self.t = 1_792_650_000.0

    def __call__(self):
        return self.t


def make(runtime_dir, script, **kw):
    clock = Clock()
    models = []

    def factory():
        m = ScriptedModel(script=[script.pop(0)] if script else [])
        models.append(m)
        return m

    stats = StatsStore(runtime_dir / "p", clock)
    moments = MomentLog(runtime_dir / "p" / "moments.jsonl", clock)
    esc = NovaEscalator(stats=stats, moments=moments, model_factory=factory, clock=clock, **kw)
    return esc, models, stats, moments, clock


def test_structured_verdict_is_parsed_and_counted(runtime_dir):
    script = [{"tool": "RuleJudgements", "input": {"judgements": [{"n": 1, "applies": True}, {"n": 3, "applies": False}]}}]
    esc, models, stats, moments, _ = make(runtime_dir, script)
    out = esc(STATE, RULES, decider_p={1: 0.52, 3: 0.4})
    assert out == {1: True, 3: False}
    assert stats.get("bedrock_calls") >= 1 and stats.get("bedrock_tokens") == 150
    assert moments.unreviewed()[-1]["kind"] == "escalated"
    assert not contains_image(models[0].calls)
    sent = json.dumps(models[0].calls[0]["messages"])
    assert "too close" in sent and "Rule 3" in sent
    usage = (runtime_dir / "p" / "bedrock-usage.jsonl").read_text().splitlines()
    assert json.loads(usage[-1])["who"] == "escalate"


def test_rate_limit_and_budget_return_none(runtime_dir):
    script = [{"tool": "RuleJudgements", "input": {"judgements": [{"n": 1, "applies": True}]}}] * 3
    esc, models, stats, moments, clock = make(runtime_dir, list(script), min_interval_s=10, daily_budget=2)
    assert esc(STATE, RULES[:1]) == {1: True}
    clock.t += 3
    assert esc(STATE, RULES[:1]) == {1: None}  # rate limited
    clock.t += 10
    assert esc(STATE, RULES[:1]) == {1: True}
    clock.t += 10
    assert esc(STATE, RULES[:1]) == {1: None}  # daily budget of 2 reached
    assert "budget" in esc.last["skipped"]


def test_model_error_returns_none(runtime_dir):
    esc, models, stats, moments, _ = make(runtime_dir, [])  # no scripted turn -> the model raises
    assert esc(STATE, RULES) == {1: None, 3: None}
    assert "error" in esc.last["skipped"]


def test_text_only():
    with pytest.raises(AssertionError):
        NovaEscalator(model_factory=lambda: None)(b"bytes", RULES)  # type: ignore[arg-type]
    assert "Rule 1:" in render_prompt(STATE, RULES)


@pytest.mark.live
def test_live_nova_lite_verdict(tmp_path):
    esc = NovaEscalator(stats=StatsStore(tmp_path, ), timeout_s=20)
    out = esc(STATE, RULES[:1])
    print("nova verdict:", out, esc.last)
    assert out[1] is True
