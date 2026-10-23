"""The reflex agent: a Strands Agent whose tools the loop calls directly.

The loop never invokes the agent's model: the Decider picks the tool and code applies the
priority order. The Agent is there so Strands interventions gate every tool call:
InterruptGate before interruptive tools, ConfirmGate before persistent ones.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from strands import Agent

from .tools import ToolContext, build_tools

INTERRUPTIVE = frozenset({"far_look_break", "glasses_reminder", "ask_user"})
NO_GATE = {"name": None, "verdict": None, "p": None}


def make_reflex_agent(ctx: ToolContext, model=None, interrupt_gate=None, confirm_gate=None) -> Agent:
    if model is None:
        from strands.models import BedrockModel
        model = BedrockModel(model_id="us.amazon.nova-lite-v1:0", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    interventions = [g for g in (interrupt_gate, confirm_gate) if g is not None]
    return Agent(model=model, tools=build_tools(ctx), interventions=interventions,
                 record_direct_tool_call=False, callback_handler=None, name="myrmidon-reflex")


@dataclass
class ToolOutcome:
    status: str  # done | denied | failed | pending_confirm
    message: str
    gate: dict
    result: dict = field(default_factory=dict)


def call_tool(agent: Agent, name: str, args: dict, interrupt_gate=None) -> ToolOutcome:
    try:
        res = getattr(agent.tool, name)(**args)
    except Exception as e:  # noqa: BLE001 - report, never crash the loop
        return ToolOutcome("failed", f"{name} failed: {type(e).__name__}: {e}", dict(NO_GATE))
    content = res.get("content", [])
    texts = [c["text"] for c in content if "text" in c]
    payload = next((c["json"] for c in content if "json" in c), {})
    first = texts[0] if texts else ""
    gate = dict(NO_GATE)
    if name in INTERRUPTIVE and interrupt_gate is not None:
        last = interrupt_gate.last
        gate = {"name": "InterruptGate", "verdict": last.get("verdict"), "p": last.get("p")}
    if first.startswith("DENIED:"):
        return ToolOutcome("denied", "Held back: " + first[len("DENIED:"):].strip() + ".", gate)
    if first.startswith("CONFIRMATION_FAILED:"):
        return ToolOutcome("denied", "Not confirmed: " + first[len("CONFIRMATION_FAILED:"):].strip(),
                           {"name": "Confirm", "verdict": "deny", "p": None})
    message = payload.get("message") or first or name
    if res.get("status") == "success":
        if payload.get("pending_confirm"):
            return ToolOutcome("pending_confirm", message, {"name": "Confirm", "verdict": "pending", "p": None}, payload)
        return ToolOutcome("done", message, gate, payload)
    return ToolOutcome("failed", message, gate, payload)
