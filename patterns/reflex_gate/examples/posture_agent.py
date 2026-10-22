"""Non-eye example of the Reflex Gate pattern: a posture coach.

Numeric facts (neck flexion, minutes slouched, minutes seated, meeting or not) are turned
into words by code, two rules become two nouls, code picks the tool by priority, and an
InterruptGate stops interruptions during meetings.

    python -m patterns.reflex_gate.examples.posture_agent --fake     # offline oracle
    python -m patterns.reflex_gate.examples.posture_agent            # real Decider on 127.0.0.1:8099
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

from strands import Agent, tool

from patterns.reflex_gate import (
    DeciderHttpClient,
    FakeDecider,
    InterruptGate,
    Rule,
    ScriptedModel,
    build_questions,
    oracle,
    select,
)

FLEXION_LIMIT_DEG = 20
SLOUCH_LIMIT_MIN = 10
SEATED_LIMIT_MIN = 50

RULES = [
    Rule(1, "posture_nudge",
         "The Neck line says slouching too long (neck bent more than 20 degrees for more than 10 minutes).",
         "Neck line ends with 'slouching too long'",
         "Neck line ends with 'posture OK' or 'not long enough yet'"),
    Rule(2, "stand_break",
         "The Seated line says a stand-up break is due (seated more than 50 minutes).",
         "Seated line ends with 'stand-up break is due'",
         "Seated line ends with 'not due yet'"),
]


@dataclass
class PostureFacts:
    label: str
    neck_flexion_deg: float
    slouch_min: float
    seated_min: float
    in_meeting: bool

    # Code does the comparisons; the Decider only reads the verdicts.
    @property
    def slouching_too_long(self) -> bool:
        return self.neck_flexion_deg > FLEXION_LIMIT_DEG and self.slouch_min > SLOUCH_LIMIT_MIN

    @property
    def stand_due(self) -> bool:
        return self.seated_min > SEATED_LIMIT_MIN


def render(f: PostureFacts) -> str:
    if f.neck_flexion_deg <= FLEXION_LIMIT_DEG:
        neck = f"bent {f.neck_flexion_deg:.0f} degrees (limit {FLEXION_LIMIT_DEG}): posture OK"
    elif f.slouch_min > SLOUCH_LIMIT_MIN:
        neck = (f"bent {f.neck_flexion_deg:.0f} degrees for {f.slouch_min:.0f} min "
                f"(limit {FLEXION_LIMIT_DEG} degrees for {SLOUCH_LIMIT_MIN} min): slouching too long")
    else:
        neck = f"bent {f.neck_flexion_deg:.0f} degrees for {f.slouch_min:.0f} min: not long enough yet"
    seated = f"{f.seated_min:.0f} min (break due after {SEATED_LIMIT_MIN} min): " + (
        "stand-up break is due" if f.stand_due else "not due yet")
    activity = ("in a video call (foreground: Microsoft Teams)" if f.in_meeting
                else "idle for 30 s (foreground: VS Code)")
    return "\n".join([
        "Measured now (computed by code):",
        f"- Neck: {neck}.",
        f"- Seated: {seated}.",
        f"- Activity: {activity}.",
    ])


STATES = [
    PostureFacts("fresh start", 8, 0, 12, False),
    PostureFacts("slouching", 28, 14, 30, False),
    PostureFacts("long sit", 10, 0, 62, False),
    PostureFacts("slouching in a meeting", 25, 15, 55, True),
]


@tool
def posture_nudge() -> dict:
    """Show a short 'sit back, chin in' nudge."""
    return {"status": "success", "content": [{"json": {"applied": True, "message": "Sit back and bring your chin in."}}]}


@tool
def stand_break() -> dict:
    """Suggest standing up for two minutes."""
    return {"status": "success", "content": [{"json": {"applied": True, "message": "Stand up and stretch for 2 minutes."}}]}


def run(fake: bool, url: str = "http://127.0.0.1:8099/v1/systemone") -> list[dict]:
    current: dict = {}
    if fake:
        preds = {"rule_1": lambda f: f.slouching_too_long, "rule_2": lambda f: f.stand_due}
        decider = FakeDecider(oracle(lambda name: preds[name](current["f"]),
                                     lambda: not current["f"].in_meeting))
    else:
        decider = DeciderHttpClient(url)
    gate = InterruptGate(decider, state_provider=lambda: current["text"],
                         interruptive_tools={"posture_nudge", "stand_break"})
    agent = Agent(model=ScriptedModel(fail_if_called=True), tools=[posture_nudge, stand_break],
                  interventions=[gate], record_direct_tool_call=False, callback_handler=None)
    out = []
    for f in STATES:
        current["f"], current["text"] = f, render(f)
        resp = decider.ask(current["text"], build_questions(RULES))
        sel = select(RULES, resp["answers"])
        row = {"state": f.label, "policy": sel.policy, "tool": sel.tool, "reason": sel.reason,
               "rule_p": {v.n: v.p for v in sel.verdicts}, "gate": None, "result": None}
        if sel.tool:
            gate.prime(sel.interrupt_p)
            result = getattr(agent.tool, sel.tool)()
            text = " ".join(c.get("text", "") for c in result["content"] if "text" in c)
            row["gate"] = dict(gate.last)
            row["result"] = "denied" if text.startswith("DENIED:") else result["status"]
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> list[dict]:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fake", action="store_true", help="offline FakeDecider oracle")
    ap.add_argument("--url", default="http://127.0.0.1:8099/v1/systemone")
    a = ap.parse_args(argv)
    rows = run(a.fake, a.url)
    for i, r in enumerate(rows, 1):
        gate = r["gate"]
        g = f" gate={gate['verdict']} p={gate['p']:.2f} -> {r['result']}" if gate else ""
        ps = " ".join(f"r{n}={p:.2f}" for n, p in r["rule_p"].items())
        print(f"state {i} ({r['state']}): policy={r['policy']} tool={r['tool'] or '-'} [{ps}]{g}")
    return rows


if __name__ == "__main__":
    main()
