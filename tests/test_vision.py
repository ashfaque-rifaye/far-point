"""Vision mode (off by default): the S2-measured request, the auto flag, and how answers feed
the glasses rule, the gaze and the signals. No GPU: FakeDecider answers the image questions."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from farpoint.config import Settings
from farpoint.contract import errors
from farpoint.doctrine import DoctrineStore, Limits, Profile
from farpoint.facts import Facts, render_state
from farpoint.runtime import Runtime
from farpoint.signals import SensorSample, SignalTracker
from farpoint.vision import GATED, S2_QUESTIONS, S2_STATE, resolve_vision, s2_allows_vision, tri, vision_questions
from patterns.reflex_gate import DeciderHttpClient, FakeDecider

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

ACROBAT = dict(process="acrobat.exe", title="paper.pdf - Adobe Acrobat Reader", idle_s=30, fullscreen=False)


def test_spike_s2_asks_exactly_what_the_loop_asks():
    import spike_s2
    assert spike_s2.QUESTIONS is S2_QUESTIONS and spike_s2.STATE == S2_STATE and spike_s2.GATED == GATED
    q = vision_questions()
    assert set(q) == {"glasses_on", "rubbing_eyes", "looking_far_away", "video_call"}
    assert {k: q[k] for k in S2_QUESTIONS} == S2_QUESTIONS


def test_auto_flag_needs_s2_pass_and_vision_server(tmp_path):
    path = tmp_path / "s2_decision.json"
    assert resolve_vision(None, {"vision": True}, path)[0] is False  # no decision file
    path.write_text(json.dumps({"pass": False, "vision_enabled": False}))
    assert resolve_vision(None, {"vision": True}, path)[0] is False
    path.write_text(json.dumps({"pass": True, "vision_enabled": True}))
    assert s2_allows_vision(path)
    assert resolve_vision(None, {"vision": False}, path) == (
        False, "text-only: S2 passed, but the Decider server does not run with --vision")
    assert resolve_vision(None, {"vision": True}, path)[0] is True
    assert resolve_vision(False, {"vision": True}, path)[0] is False
    assert resolve_vision(True, None, path)[0] is True
    assert (tri(0.9), tri(0.5), tri(0.1), tri(None)) == (True, None, False, None)


def test_images_never_go_to_a_non_local_decider():
    with pytest.raises(ValueError):
        DeciderHttpClient("http://10.0.0.5:8099/v1/systemone").ask("state", {"q": {"type": "noul",
                                                                                   "instructions": "x"}},
                                                                  images=["abc"])


def test_glasses_line_and_rule_with_vision():
    from farpoint.doctrine import default_doctrine
    from farpoint.predicates import PREDICATES
    d = default_doctrine().model_copy(update={"profile": Profile(glasses_for_screen="yes")})
    base = dict(face=True, distance_cm=52, squint_ratio=0.95, usual_distance_cm=52, glasses_prescribed="yes")
    off = Facts(**base, vision=True, glasses_on=False)
    on = Facts(**base, vision=True, glasses_on=True, glasses_off_signs=True)
    unsure = Facts(**base, vision=True, glasses_on=None)
    assert "worn: no (camera)" in render_state(off, d) and ": reminder due." in render_state(off, d)
    assert "worn: yes (camera)" in render_state(on, d) and "no reminder needed" in render_state(on, d)
    assert "worn: not sure (camera)" in render_state(unsure, d)
    assert "worn: not checked (text-only mode)" in render_state(Facts(**base), d)
    assert PREDICATES["glasses_reminder"](off, d.limits) and not PREDICATES["glasses_reminder"](on, d.limits)


def test_vision_far_gaze_counts_as_looking_away():
    tr = SignalTracker(Limits())
    t = 1_792_650_000.0
    for i in range(10):
        tr.update(t + i / 10, SensorSample(True, 52, 0.27, 0.97, 0.0, 0.0, 120))
    assert tr.looking_at_screen is True
    tr.set_vision(t + 1, 0.9, False)
    assert tr.looking_at_screen is False
    tr.update(t + 7, SensorSample(True, 52, 0.27, 0.97, 0.0, 0.0, 120))  # vision answer now stale
    assert tr.looking_at_screen is True


class Sim:
    def __init__(self, tmp_path, fn):
        tmp_path.mkdir(parents=True, exist_ok=True)
        trace = tmp_path / "trace.jsonl"
        trace.write_text('{"kind":"header","version":1}\n')
        DoctrineStore(tmp_path / "replay" / "profile").update_profile(glasses_for_screen="yes")
        self.decider = FakeDecider(lambda state, name, q: fn(self, state, name))
        s = Settings(mode="replay", trace=trace, runtime_dir=tmp_path, no_bedrock=True, vision=True)
        self.rt = Runtime(s, decider=self.decider, bedrock_available=False, deny_without_client=False)
        self.rt.loop.period_s = 1e9
        self.rt.loop.image_provider = lambda: "ZmFrZS1qcGVn"  # stand-in base64; FakeDecider never decodes it
        self.events = []
        self.rt.bus.add_listener(self.events.append)
        self.t, self.last = 0.0, {"process": None}

    def run(self, seconds):
        for _ in range(int(seconds * 10)):
            self.t += 0.1
            self.rt.source.feed(dict(t=self.t, face=True, distance_cm=52.0, ear=0.27, squint_ratio=0.96, yaw=0.0,
                                     pitch=0.0, luma=120.0, theme="dark", brightness=50, **ACROBAT), self.last)


def test_vision_request_feeds_glasses_rule_signals_and_decision(tmp_path):
    def fn(sim, state, name):
        if state == S2_STATE:  # the image request
            return {"glasses_on": 0.08, "looking_far_away": 0.1, "rubbing_eyes": 0.05, "video_call": 0.1}[name]
        if name == "interrupt_ok":
            return 0.9
        rule = sim.rt.store.active.rule(int(name.split("_")[1]))
        return 0.92 if rule.tool == "glasses_reminder" and "reminder due" in state else 0.06

    sim = Sim(tmp_path, fn)
    assert sim.rt.hello()["decider"]["vision"] is True
    sim.run(3)
    d = sim.rt.loop.tick()
    image_calls = [c for c in sim.decider.calls if c["images"]]
    assert len(image_calls) == 1 and image_calls[0]["state"] == S2_STATE
    assert set(image_calls[0]["questions"]) == set(vision_questions())
    text_calls = [c for c in sim.decider.calls if not c["images"]]
    assert text_calls and all("glasses_on" not in c["questions"] for c in text_calls)
    assert d["answers"]["vision"] == {"glasses_on": 0.08, "rubbing_eyes": 0.05, "looking_far": 0.1, "video_call": 0.1}
    assert "worn: no (camera)" in d["state_text"] and d["rule_ref"] == "rule 2"
    action = [e["data"] for e in sim.events if e["type"] == "action"][-1]
    assert action["tool"] == "glasses_reminder" and action["status"] == "done"
    time.sleep(0.15)  # the bus throttles signals to 10 Hz of wall time
    sim.run(0.5)
    sig = [e["data"] for e in sim.events if e["type"] == "signals"][-1]
    assert sig["glasses_on"] is False
    bad = [(e["type"], errors(e, "ServerEvent")) for e in sim.events if errors(e, "ServerEvent")]
    assert bad == []


def test_vision_request_failure_still_decides(tmp_path):
    def fn(sim, state, name):
        if state == S2_STATE:
            raise ValueError("this engine has no vision tower")
        return 0.9 if name == "interrupt_ok" else 0.05

    sim = Sim(tmp_path, fn)
    sim.run(3)
    d = sim.rt.loop.tick()
    assert d["source"] == "decider" and "vision" not in d["answers"]
    assert "worn: not sure (camera)" in d["state_text"]


def test_text_only_by_default_in_live_mode_without_s2_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("FARPOINT_VISION", raising=False)
    s = Settings(mode="live", runtime_dir=tmp_path, no_bedrock=True, dry_run=True)
    assert s.vision is None
    fake = FakeDecider(lambda *a: 0.5)
    fake.health_info = lambda timeout=2.0: {"status": "ok", "vision": True}
    rt = Runtime(s, decider=fake, bedrock_available=False)
    assert rt.settings.vision is False and "S2 has not passed" in rt.vision_reason
    assert rt.loop.image_provider is None and rt.source.keep_frame is False
    rt.coach.close()


def test_decide_s2_writes_decision_and_spike_results_block(tmp_path):
    import spike_s2
    score = tmp_path / "s2_score.json"
    cap = tmp_path / "s2_capture.json"
    md = tmp_path / "SPIKE_RESULTS.md"
    md.write_text("# x\n\n### Re-opening S2\n\ntext\n\n## Notes for the build\n\n- a\n")
    cap.write_text(json.dumps({"glasses_source": "prop", "glasses_for_screen": "no"}))
    score.write_text(json.dumps({"summary": {"n": 48, "accuracy": {"glasses_on": 0.9, "rubbing_eyes": 0.7,
                                                                   "looking_far_away": 0.86},
                                             "client_s": {"p50": 0.52}}}))
    out = tmp_path / "s2_decision.json"
    d = spike_s2.decide_s2(score, cap, out, md, now=datetime(2026, 10, 23, 9, 30))
    assert d["pass"] is True and d["vision_enabled"] is True and d["glasses_source"] == "prop"
    assert s2_allows_vision(out)
    text = md.read_text()
    assert text.count(spike_s2.MARK_START) == 1 and "PASS" in text and text.index("PASS") < text.index("## Notes")
    score.write_text(json.dumps({"summary": {"n": 48, "accuracy": {"glasses_on": 0.84, "rubbing_eyes": 0.9,
                                                                   "looking_far_away": 0.95}}}))
    d2 = spike_s2.decide_s2(score, cap, out, md)
    assert d2["pass"] is False and not s2_allows_vision(out)
    text = md.read_text()
    assert text.count(spike_s2.MARK_START) == 1 and "FAIL" in text and "PASS" not in text
