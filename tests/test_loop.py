"""Reflex loop, ticked by hand over synthetic numeric readings (no GPU, AWS or camera)."""
from myrmidon.config import Settings
from myrmidon.contract import errors
from myrmidon.predicates import PREDICATES
from myrmidon.runtime import Runtime
from patterns.reflex_gate import FakeDecider

ACROBAT = dict(process="acrobat.exe", title="paper.pdf - Adobe Acrobat Reader", idle_s=30, fullscreen=False)
TEAMS = dict(process="ms-teams.exe", title="Standup | Microsoft Teams", idle_s=30, fullscreen=False)


class Sim:
    def __init__(self, tmp_path, decider_fn=None, escalator=None, decider=None, header=None):
        tmp_path.mkdir(parents=True, exist_ok=True)
        trace = tmp_path / "trace.jsonl"
        trace.write_text('{"kind":"header","version":1}\n')
        s = Settings(mode="replay", trace=trace, runtime_dir=tmp_path, no_bedrock=True,
                     fake_decider=decider is None and decider_fn is None)
        if decider_fn is not None:
            decider = FakeDecider(lambda state, name, q: decider_fn(self, name))
        self.rt = Runtime(s, decider=decider, escalator=escalator, bedrock_available=False, deny_without_client=False)
        self.rt.loop.period_s = 1e9  # tick by hand
        self.events = []
        self.rt.bus.add_listener(self.events.append)
        self.t = 0.0
        self.last = {"process": None}

    def run(self, seconds, distance=55.0, ratio=1.0, yaw=0.0, luma=120.0, face=True, theme="light", brightness=60,
            app=ACROBAT):
        for _ in range(int(round(seconds * 10))):
            self.t += 0.1
            row = dict(t=self.t, face=face, distance_cm=distance if face else None, ear=0.28 * ratio,
                       squint_ratio=ratio if face else None, yaw=yaw, pitch=0.0, luma=luma, theme=theme,
                       brightness=brightness, **app)
            self.rt.source.feed(row, self.last)

    def tick(self):
        return self.rt.loop.tick()

    def of(self, kind):
        return [e["data"] for e in self.events if e["type"] == kind]

    def oracle(self, name):
        f, d = self.rt.loop.current_facts, self.rt.store.active
        if name == "interrupt_ok":
            return 0.9 if f.interrupt_ok_hint in (None, True) else 0.1
        rule = d.rule(int(name.split("_")[1]))
        return 0.92 if PREDICATES[rule.tool](f, d.limits) else 0.06

    def assert_schema(self):
        bad = [(e["type"], errors(e, "ServerEvent")) for e in self.events if errors(e, "ServerEvent")]
        assert bad == []


def test_too_close_enlarges_then_verifies_worked(tmp_path):
    sim = Sim(tmp_path)
    sim.run(5, distance=55)
    assert sim.tick()["policy"] == "quiet"
    sim.run(6, distance=27, ratio=0.7)
    d = sim.tick()
    assert (d["policy"], d["answers"]["next_action"]["choice"], d["rule_ref"]) == ("act", "enlarge_text", "rule 1")
    assert "too close, enlarging needed." in d["state_text"] and d["source"] == "decider"
    a = sim.of("action")[-1]
    assert (a["tool"], a["status"], a["decision_id"]) == ("enlarge_text", "done", d["id"])
    assert a["gate"] == {"name": None, "verdict": None, "p": None}
    assert sim.rt.actuators.zoom.zoom_step() == 1
    sim.run(31, distance=45, ratio=0.95)
    v = sim.of("verification")[-1]
    assert v["action_id"] == a["id"] and v["outcome"] == "worked" and v["after"]["distance_cm"] == 45
    assert sim.rt.stats.get("adaptations") == 1 and sim.rt.stats.get("adaptations_worked") == 1
    sim.assert_schema()


def test_dark_room_light_theme_switches_dark_mode(tmp_path):
    sim = Sim(tmp_path)
    sim.run(6, luma=30, theme="light")
    d = sim.tick()
    assert d["answers"]["next_action"]["choice"] == "dark_mode" and d["rule_ref"] == "rule 3"
    assert "Theme: light, in a dark room: mismatch, dark mode needed." in d["state_text"]
    assert sim.of("action")[-1]["status"] == "done" and sim.rt.actuators.state()["theme"] == "dark"
    sim.run(3, luma=30, theme="light")  # the trace keeps saying light; Myrmidon's change sticks
    assert sim.tick()["policy"] == "quiet"
    sim.assert_schema()


def test_unsure_higher_rule_escalates(tmp_path):
    calls = []

    def esc_true(state_text, rules, decider_p):
        calls.append(([r.n for r in rules], decider_p))
        return {r.n: True for r in rules}

    def fn(sim, name):
        return 0.5 if name == "rule_1" else sim.oracle(name)

    sim = Sim(tmp_path, decider_fn=fn, escalator=esc_true)
    sim.run(6, luma=30, theme="light")
    d = sim.tick()
    assert calls and calls[0][0] == [1] and calls[0][1] == {1: 0.5}
    assert d["policy"] == "act" and d["answers"]["next_action"]["choice"] == "enlarge_text"
    assert d["escalation"]["verdicts"] == {"1": True}
    sim.assert_schema()


def test_unsure_with_no_verdict_fails_quiet_and_logs_moment(tmp_path):
    def fn(sim, name):
        return 0.5 if name == "rule_1" else sim.oracle(name)

    sim = Sim(tmp_path, decider_fn=fn, escalator=lambda s, rules, p: {r.n: None for r in rules})
    sim.run(6, luma=30, theme="light")
    d = sim.tick()
    assert d["policy"] == "quiet" and "fail quiet" in d["reason"] and sim.of("action") == []
    sim2 = Sim(tmp_path / "b", decider_fn=fn, escalator=None)
    sim2.run(6, luma=30, theme="light")
    d2 = sim2.tick()
    assert d2["policy"] == "quiet"
    assert any(m["kind"] == "unsure" for m in sim2.rt.moments.unreviewed())


def test_decider_timeout_is_fallback_quiet(tmp_path):
    sim = Sim(tmp_path, decider=FakeDecider(lambda *a: 0.9, fail=TimeoutError("timed out")))
    sim.run(6, distance=27)
    d = sim.tick()
    assert (d["source"], d["policy"]) == ("fallback", "quiet") and sim.of("action") == []
    sim.assert_schema()


def test_break_due_in_video_call_is_denied(tmp_path):
    sim = Sim(tmp_path)
    sim.rt.tracker.seed_bout(45 * 60)
    sim.run(3, distance=50, app=TEAMS)
    d = sim.tick()
    assert d["answers"]["next_action"]["choice"] == "far_look_break" and d["answers"]["interrupt_ok"]["p"] < 0.5
    a = sim.of("action")[-1]
    assert a["status"] == "denied" and a["gate"]["name"] == "InterruptGate" and a["gate"]["verdict"] == "deny"
    assert not sim.rt.breaks.is_active()
    sim.run(31, distance=50, app=ACROBAT)  # call over, retry backoff passed
    d2 = sim.tick()
    assert d2["answers"]["next_action"]["choice"] == "far_look_break"
    assert sim.of("action")[-1]["status"] == "done" and sim.rt.breaks.is_active()
    sim.run(21, distance=50, yaw=40, app=ACROBAT)
    assert sim.of("break")[-1]["phase"] == "verified" and sim.of("verification")[-1]["outcome"] == "worked"
    sim.assert_schema()


def test_demoted_tool_is_skipped(tmp_path):
    sim = Sim(tmp_path)
    for _ in range(3):
        sim.rt.prefs.record("enlarge_text", "pdf", "no_change")
    sim.run(6, distance=27)
    d = sim.tick()
    assert d["policy"] == "quiet"
    assert {"n": 1, "tool": "enlarge_text", "why": "demoted in this app"} in d["skipped"]
    assert any(m["kind"] == "demoted" for m in sim.rt.moments.unreviewed())
    sim.assert_schema()
