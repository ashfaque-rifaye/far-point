"""Pins the Strands behaviour the pattern relies on: interventions DO run on direct
`agent.tool.X()` calls (strands-agents 1.62.0), and the model is never invoked."""
from strands import Agent, tool

from patterns.reflex_gate import ConfirmGate, FakeDecider, InterruptGate, ScriptedModel

RAN: list[str] = []


@tool
def probe(note: str = "") -> dict:
    """Interruptive probe tool."""
    RAN.append(f"probe:{note}")
    return {"status": "success", "content": [{"json": {"applied": True, "message": "ran"}}]}


@tool
def persist(value: int = 0) -> dict:
    """Persistent probe tool behind a Confirm."""
    RAN.append(f"persist:{value}")
    return {"status": "success", "content": [{"json": {"applied": True, "message": "saved"}}]}


@tool
def harmless() -> str:
    """Not gated."""
    RAN.append("harmless")
    return "ok"


def make(answer: bool, interrupt_p: float = 0.9):
    model = ScriptedModel(script=[], fail_if_called=True)
    decider = FakeDecider(lambda state, name, q: interrupt_p)
    ig = InterruptGate(decider, state_provider=lambda: "Activity: idle for 30 s", interruptive_tools={"probe"})
    asked = []

    def ask_human(tool_name, prompt, args):
        asked.append((tool_name, prompt, args))
        return answer

    cg = ConfirmGate({"persist": lambda a: f"Save value {a.get('value')}?"}, ask_human)
    agent = Agent(model=model, tools=[probe, persist, harmless], interventions=[ig, cg],
                  record_direct_tool_call=False, callback_handler=None)
    return agent, model, decider, ig, cg, asked


def text_of(result) -> str:
    return " ".join(c.get("text", "") for c in result["content"] if "text" in c)


def test_low_primed_p_denies_without_running_tool():
    RAN.clear()
    agent, model, decider, ig, _, _ = make(answer=True)
    ig.prime(0.2)
    r = agent.tool.probe(note="x")
    assert r["status"] == "error"
    assert text_of(r).startswith("DENIED:")
    assert RAN == []
    assert ig.last == {"name": "InterruptGate", "verdict": "deny", "p": 0.2}
    assert decider.calls == []  # primed answer reused, no second Decider call
    assert model.attempts == 0


def test_high_primed_p_runs_tool():
    RAN.clear()
    agent, model, decider, ig, _, _ = make(answer=True)
    ig.prime(0.9)
    r = agent.tool.probe(note="y")
    assert r["status"] == "success"
    assert RAN == ["probe:y"]
    assert ig.last["verdict"] == "proceed"
    assert decider.calls == []
    assert model.attempts == 0


def test_unprimed_gate_asks_decider_once():
    RAN.clear()
    agent, model, decider, ig, _, _ = make(answer=True, interrupt_p=0.1)
    r = agent.tool.probe()
    assert text_of(r).startswith("DENIED:")
    assert len(decider.calls) == 1 and set(decider.calls[0]["questions"]) == {"interrupt_ok"}
    assert RAN == []


def test_confirm_gate_false_fails_confirmation():
    RAN.clear()
    agent, model, _, _, cg, asked = make(answer=False)
    r = agent.tool.persist(value=3)
    assert r["status"] == "error"
    assert text_of(r).startswith("CONFIRMATION_FAILED:")
    assert RAN == []
    assert asked == [("persist", "Save value 3?", {"value": 3})]
    assert cg.last["verdict"] == "deny"
    assert model.attempts == 0


def test_confirm_gate_true_runs_tool_and_ungated_tool_passes():
    RAN.clear()
    agent, model, *_ = make(answer=True)
    assert agent.tool.persist(value=5)["status"] == "success"
    assert agent.tool.harmless()["status"] == "success"
    assert RAN == ["persist:5", "harmless"]
    assert model.attempts == 0
    assert agent.messages == []  # record_direct_tool_call=False keeps history empty
