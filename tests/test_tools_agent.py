from myrmidon.act import Actuators
from myrmidon.agent import INTERRUPTIVE, call_tool, make_reflex_agent
from myrmidon.breaks import BreakManager
from myrmidon.bus import EventBus
from myrmidon.confirm import ConfirmBroker
from myrmidon.memory import PreferenceStore
from myrmidon.signals import SignalTracker
from myrmidon.stats import StatsStore
from myrmidon.tools import ToolContext
from patterns.reflex_gate import FakeDecider, InterruptGate, ScriptedModel


def build(runtime_dir, interrupt_p=0.9):
    bus = EventBus(validate=True)
    seen = []
    bus.add_listener(seen.append)
    clock = lambda: 1_792_650_000.0  # noqa: E731
    act = Actuators.dry(light=True, brightness=80, process="acrobat.exe")
    tracker = SignalTracker()
    stats = StatsStore(runtime_dir / "p", clock)
    breaks = BreakManager(bus, act.overlay, tracker, stats, clock)
    broker = ConfirmBroker(bus, deny_without_client=False)
    ctx = ToolContext(act, breaks, broker, bus, tracker, PreferenceStore(runtime_dir / "p" / "prefs.json"))
    gate = InterruptGate(FakeDecider(lambda s, n, q: interrupt_p), lambda: "Activity: idle", INTERRUPTIVE)
    model = ScriptedModel(fail_if_called=True)
    agent = make_reflex_agent(ctx, model=model, interrupt_gate=gate)
    return agent, model, gate, ctx, seen


def test_every_tool_runs_directly_and_model_is_never_called(runtime_dir):
    agent, model, gate, ctx, seen = build(runtime_dir)
    calls = [("enlarge_text", {"steps": 1}), ("reduce_text", {"steps": 1}), ("dim_screen", {"level": 0.5}),
             ("brighten_screen", {"level": 0.8}), ("dark_mode", {"on": True}), ("glasses_reminder", {}),
             ("far_look_break", {"target_s": 20}), ("reset", {})]
    out = {}
    for name, args in calls:
        if name in INTERRUPTIVE:
            gate.prime(0.9)
        out[name] = call_tool(agent, name, args, gate)
    assert {k: v.status for k, v in out.items()} == {k: "done" for k, _ in calls}
    assert out["enlarge_text"].result["zoom_step"] == 1
    assert out["far_look_break"].gate == {"name": "InterruptGate", "verdict": "proceed", "p": 0.9}
    assert out["dark_mode"].gate == {"name": None, "verdict": None, "p": None}
    assert ctx.actuators.state()["theme"] == "light"  # reset restored it
    assert model.attempts == 0 and agent.messages == []


def test_far_look_break_denied_with_low_interrupt_p(runtime_dir):
    agent, model, gate, ctx, seen = build(runtime_dir)
    gate.prime(0.2)
    o = call_tool(agent, "far_look_break", {"target_s": 20}, gate)
    assert o.status == "denied" and o.gate["verdict"] == "deny" and o.gate["p"] == 0.2
    assert not ctx.breaks.is_active() and not [e for e in seen if e["type"] == "break"]
    gate.prime(0.9)
    o2 = call_tool(agent, "far_look_break", {"target_s": 20}, gate)
    assert o2.status == "done" and ctx.breaks.is_active()


def test_ask_user_returns_pending_confirm_immediately(runtime_dir):
    agent, model, gate, ctx, seen = build(runtime_dir)
    answers = []
    ctx.on_ask_answer = lambda aid, ok: answers.append((aid, ok))
    ctx.current = {"action_id": "a_000009", "category": "pdf"}
    gate.prime(0.9)
    o = call_tool(agent, "ask_user", {"question": "Take a break?"}, gate)
    assert o.status == "pending_confirm" and o.gate == {"name": "Confirm", "verdict": "pending", "p": None}
    req = [e for e in seen if e["type"] == "confirm_request"][-1]["data"]
    assert ctx.broker.resolve(req["request_id"], True)
    assert answers == [("a_000009", True)] and ctx.breaks.is_active()


def test_zoom_not_available_is_failed(runtime_dir):
    agent, model, gate, ctx, seen = build(runtime_dir)
    ctx.actuators.zoom.window.set("ms-teams.exe", "Call | Microsoft Teams")
    o = call_tool(agent, "enlarge_text", {"steps": 1}, gate)
    assert o.status == "failed" and "not available" in o.message
