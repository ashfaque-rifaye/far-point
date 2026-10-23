"""Myrmidon's ACT tools as Strands tools.

The reflex loop calls them directly (`agent.tool.<name>(...)`), so Strands interventions
(InterruptGate, ConfirmGate) run first. Every change is reversible (see `myrmidon.act`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from strands import tool


@dataclass
class ToolContext:
    actuators: object
    breaks: object
    broker: object
    bus: object
    tracker: object
    prefs: object
    moments: object | None = None
    # Set by the loop right before each call: {"action_id", "decision_id", "category"}.
    current: dict = field(default_factory=dict)
    # Loop hook: re-publish an ask_user action once the human answers.
    on_ask_answer: Callable[[str, bool], None] | None = None


def _result(applied: bool, message: str, args: dict, ok: bool | None = None, **extra) -> dict:
    status = "success" if (applied if ok is None else ok) else "error"
    return {"status": status, "content": [{"json": {"applied": applied, "message": message, "args": args, **extra}}]}


def build_tools(ctx: ToolContext) -> list:
    act = ctx.actuators

    @tool
    def enlarge_text(steps: int = 1) -> dict:
        """Enlarge text in the foreground app by `steps` zoom steps (reversible; restored on exit)."""
        applied, msg, net = act.zoom.step(+1, steps)
        if applied:
            msg = "Text enlarged one step so you can lean back." if steps == 1 else msg
        return _result(applied, msg, {"steps": steps}, zoom_step=net)

    @tool
    def reduce_text(steps: int = 1) -> dict:
        """Undo Myrmidon's text zoom by `steps` steps."""
        applied, msg, net = act.zoom.step(-1, steps)
        if applied:
            msg = "You have read comfortably for a while, so text went back one step."
        return _result(applied, msg, {"steps": steps}, zoom_step=net)

    @tool
    def dim_screen(level: float = 0.5) -> dict:
        """Dim the internal display to `level` (0-1) of full brightness."""
        target = round(max(0.05, min(1.0, level)) * 100)
        cur = act.brightness.current(fresh=True)
        if cur is None:
            return _result(False, "Screen brightness is not adjustable on this display.", {"level": level})
        if cur <= target:
            return _result(False, f"Screen brightness is already {cur}%.", {"level": level})
        applied, msg = act.brightness.set_level(target)
        return _result(applied, f"Screen dimmed to {target}% for the dark room." if applied else msg, {"level": level})

    @tool
    def brighten_screen(level: float = 0.8) -> dict:
        """Brighten the internal display to `level` (0-1) of full brightness."""
        target = round(max(0.05, min(1.0, level)) * 100)
        cur = act.brightness.current(fresh=True)
        if cur is None:
            return _result(False, "Screen brightness is not adjustable on this display.", {"level": level})
        if cur >= target:
            return _result(False, f"Screen brightness is already {cur}%.", {"level": level})
        applied, msg = act.brightness.set_level(target)
        return _result(applied, f"Screen brightened to {target}% for the bright room." if applied else msg,
                       {"level": level})

    @tool
    def dark_mode(on: bool = True) -> dict:
        """Switch Windows apps to dark (on=True) or light theme. Restored on exit."""
        applied, msg = act.theme.set_dark(on)
        if applied and on:
            msg = "Switched apps to dark mode: less glare in a dark room."
        return _result(applied, msg, {"on": on})

    @tool
    def far_look_break(target_s: int = 20) -> dict:
        """Start a camera-verified far-look break: look ~6 m away for `target_s` seconds."""
        if ctx.breaks.is_active():
            return _result(False, "A break is already running.", {"target_s": target_s})
        bid = ctx.breaks.start(target_s, action_id=ctx.current.get("action_id"),
                               category=ctx.current.get("category", "other"))
        return _result(True, f"Break time: look about 6 m away for {target_s} s. The camera counts it.",
                       {"target_s": target_s}, break_id=bid)

    @tool
    def glasses_reminder() -> dict:
        """Show a gentle reminder to put on the glasses prescribed for screen work."""
        text = "You are leaning in and squinting. If your glasses for screen work are nearby, now is a good time."
        act.overlay.toast(text, seconds=8)
        ctx.bus.toast("info", text)
        return _result(True, "Reminder shown: glasses for screen work.", {})

    @tool
    def ask_user(question: str) -> dict:
        """Ask the user a yes/no question in the dashboard. Returns at once; the answer arrives later."""
        action_id = ctx.current.get("action_id")
        category = ctx.current.get("category", "other")

        def on_answer(approve: bool) -> None:
            ctx.prefs.record_ask(question, approve)
            if approve:
                ctx.breaks.start(20, action_id=None, category=category)
            if ctx.on_ask_answer is not None and action_id:
                ctx.on_ask_answer(action_id, approve)

        rid = ctx.broker.request_async("How are your eyes?", question, on_answer)
        if rid is None:
            return _result(False, "No dashboard is connected, so Myrmidon did not ask.", {"question": question})
        return _result(False, f"Asked you: {question}", {"question": question}, ok=True, pending_confirm=True,
                       request_id=rid)

    @tool
    def reset() -> dict:
        """Undo every change Myrmidon made (zoom, brightness, theme)."""
        out = act.restore_all()
        return _result(all(out.values()), "Everything Myrmidon changed is back to how it was.", {}, restored=out)

    return [enlarge_text, reduce_text, dim_screen, brighten_screen, dark_mode, far_look_break,
            glasses_reminder, ask_user, reset]
