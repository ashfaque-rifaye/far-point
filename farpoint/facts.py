"""Facts the loop measured, rendered in words with the comparisons already done.

The Decider never does arithmetic: every line ends with the verdict the rule criteria
quote ("too close", "break is due", "mismatch", ...). Strain is counted in code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .doctrine import Doctrine, Limits

ROOM_WORDS = {"dark": "dark", "dim": "dim", "normal": "normal indoor light", "bright": "bright"}
STRAIN_LEVELS = ("relaxed", "mild", "strong")

# The exact lines render_state writes and the verdict words each can end with. Rules (from
# Bedrock, the user or proposals) may only reference these.
FACT_LINE_GUIDE = """\
- "Viewing distance: ...": ends with "too close, enlarging needed" | "too close, but this app has no zoom control" | "no enlarging needed yet" | "no enlarging needed" | "no face visible"
- "Near-work bout: ...": ends with "break is due" | "break not due yet"
- "Eyes: ...": "squinting for N s (eye opening P% of your baseline)" | "not squinting (...)" | "not measured"
- "Blink rate: ...": ends with "low" | "normal" | "still measuring"
- "Glasses: prescribed for screen work: yes|no|unknown; worn: ...; signs consistent with glasses off: yes (...)|no": ends with "reminder due" | "no reminder needed"
- "Room light: dark" | "dim" | "normal indoor light" | "bright" (estimated from camera brightness)
- "Theme: light, in a dark room: mismatch, dark mode needed" | "Theme: light: no change needed" | "Theme: dark: no change needed"
- "Screen brightness: N%: dimming needed (...)" | "brightening needed (...)" | "no change needed" | "not adjustable"
- "Text zoom: Far Point zoom +N in APP (category); zoom control available" | "zoom control not available for this app"
- "Relaxed reading: N min ..., Far Point zoom +N": ends with "text can go back one step" | "no change needed"
- "Squint despite zoom ...": ends with "yes" | "no"
- "Activity: ...": idle | between tasks | just switched windows | typing in a burst | in a video call | watching a (fullscreen) video
- "Local time: HH:MM (morning|afternoon|evening|night)" (night is 21:00-05:00)
- "Profile (user's own words): ..." (only when the user described their eyes)"""


@dataclass
class Facts:
    face: bool = False
    distance_cm: float | None = None
    under_near_s: float = 0.0
    bout_min_now: float = 0.0
    squinting: bool = False
    squinting_s: float = 0.0
    squint_ratio: float | None = None
    blink_per_min: float | None = None
    looking_at_screen: bool | None = None
    usual_distance_cm: float | None = None
    glasses_off_signs: bool = False
    room: str = "normal"  # dark | dim | normal | bright
    brightness_pct: int | None = None
    theme: str = "light"  # light | dark
    app_name: str = ""
    app_category: str = "other"
    zoom_available: bool = False
    zoom_step: int = 0
    relaxed_min_now: float = 0.0
    activity: str = "idle (no foreground window information)"
    interrupt_ok_hint: bool | None = None
    glasses_on: bool | None = None
    glasses_prescribed: str = "unknown"  # yes | no | unknown (from the doctrine profile)
    local_time: str = ""  # "HH:MM", set by the loop from its clock

    def to_dict(self) -> dict:
        return asdict(self)


def too_close(f: Facts, L: Limits) -> bool:
    return f.face and f.distance_cm is not None and f.distance_cm < L.near_cm and f.under_near_s > L.near_s


def break_due(f: Facts, L: Limits) -> bool:
    return f.bout_min_now >= L.bout_min


def low_blink(f: Facts, L: Limits) -> bool:
    return f.blink_per_min is not None and f.blink_per_min < L.low_blink_per_min


def relaxed_long_enough(f: Facts, L: Limits) -> bool:
    return f.relaxed_min_now >= L.relaxed_min


def squint_despite_zoom(f: Facts) -> bool:
    return f.squinting and f.squinting_s > 60 and f.zoom_step >= 2


def part_of_day(hhmm: str) -> str:
    h = int(hhmm.split(":")[0])
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 18:
        return "afternoon"
    if 18 <= h < 21:
        return "evening"
    return "night"


def glasses_reminder_due(f: Facts) -> bool:
    return f.glasses_prescribed == "yes" and f.glasses_off_signs


def text_can_go_back(f: Facts, L: Limits) -> bool:
    return f.zoom_step > 0 and relaxed_long_enough(f, L)


def dimming_needed(f: Facts, L: Limits) -> bool:
    return f.brightness_pct is not None and f.room == "dark" and f.brightness_pct >= L.dim_pct_high


def brightening_needed(f: Facts, L: Limits) -> bool:
    return f.brightness_pct is not None and f.room == "bright" and f.brightness_pct <= L.bright_pct_low


def brightness_verdict(f: Facts, L: Limits) -> str:
    # Action words, not descriptions: in a probe against the real Decider, "dimming needed" /
    # "no change needed" separated at p 0.97 / 0.10, while "high for a dark room" / "suits the
    # room" left the no-change case unsure (p 0.43) whenever the room line said dark.
    if f.brightness_pct is None:
        return "not adjustable"
    if dimming_needed(f, L):
        return "dimming needed (too bright for a dark room)"
    if brightening_needed(f, L):
        return "brightening needed (too dim for a bright room)"
    return "no change needed"


def _num(x: float) -> str:
    return f"{x:.0f}"


def render_state(f: Facts, doctrine: Doctrine) -> str:
    L = doctrine.limits
    prof = doctrine.profile
    lines = ["Measured now (code computed every number and comparison):"]

    # Each line ends with ONE verdict phrase that a rule can quote. Conditions that a default
    # rule combines are folded into a single line by code: probes against the real Decider
    # showed it reads a single line's verdict reliably but leaves cross-line ANDs unsure.
    # "X needed" / "no X needed" verdicts separated best in probes (p ~0.96 vs ~0.21).
    if not f.face or f.distance_cm is None:
        lines.append("- Viewing distance: no face visible.")
    elif too_close(f, L):
        tail = "too close, enlarging needed" if f.zoom_available else "too close, but this app has no zoom control"
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm, under {_num(L.near_cm)} cm for "
                     f"{_num(f.under_near_s)} s (limit {_num(L.near_s)} s): {tail}.")
    elif f.distance_cm < L.near_cm:
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm for {_num(f.under_near_s)} s "
                     f"(limit {_num(L.near_s)} s under {_num(L.near_cm)} cm): no enlarging needed yet.")
    else:
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm: no enlarging needed.")

    bout = (f"- Near-work bout: {_num(f.bout_min_now)} min closer than {_num(L.bout_cm)} cm "
            f"(break due at {_num(L.bout_min)} min): ")
    lines.append(bout + ("break is due." if break_due(f, L) else "break not due yet."))

    if not f.face or f.squint_ratio is None:
        lines.append("- Eyes: not measured (no face visible).")
    elif f.squinting:
        lines.append(f"- Eyes: squinting for {_num(f.squinting_s)} s (eye opening "
                     f"{_num(f.squint_ratio * 100)}% of your baseline).")
    else:
        lines.append(f"- Eyes: not squinting (eye opening {_num(f.squint_ratio * 100)}% of your baseline).")

    if f.blink_per_min is None:
        lines.append("- Blink rate: still measuring.")
    else:
        lines.append(f"- Blink rate: {_num(f.blink_per_min)} per minute (normal is {_num(L.low_blink_per_min)} "
                     f"or more): " + ("low." if low_blink(f, L) else "normal."))

    if f.glasses_on is None:
        worn = "worn: not checked (text-only mode)"
    else:
        worn = "worn: yes" if f.glasses_on else "worn: no"
    if f.usual_distance_cm is None:
        signs = "signs consistent with glasses off: no (usual distance not learned yet)"
    elif f.glasses_off_signs:
        lean = (f.usual_distance_cm - f.distance_cm) if f.distance_cm is not None else 0
        signs = (f"signs consistent with glasses off: yes (leaning in {_num(lean)} cm closer than your usual "
                 f"{_num(f.usual_distance_cm)} cm, and squinting)")
    else:
        signs = "signs consistent with glasses off: no"
    # The loop copies the doctrine profile into the facts; fall back to the profile here.
    prescribed = prof.glasses_for_screen if f.glasses_prescribed == "unknown" else f.glasses_prescribed
    due = prescribed == "yes" and f.glasses_off_signs
    verdict = "reminder due" if due else "no reminder needed"
    lines.append(f"- Glasses: prescribed for screen work: {prescribed}; {worn}; {signs}: {verdict}.")

    lines.append(f"- Room light: {ROOM_WORDS.get(f.room, f.room)} (estimated from camera brightness).")
    if f.room == "dark" and f.theme == "light":
        lines.append("- Theme: light, in a dark room: mismatch, dark mode needed.")
    else:
        lines.append(f"- Theme: {f.theme}: no change needed.")

    bv = brightness_verdict(f, L)
    if f.brightness_pct is None:
        lines.append("- Screen brightness: not adjustable on this display.")
    else:
        lines.append(f"- Screen brightness: {f.brightness_pct}%: {bv}.")

    app = f.app_name or "unknown app"
    zoom = f"Far Point zoom {f.zoom_step:+d} in {app} ({f.app_category}); "
    zoom += "zoom control available." if f.zoom_available else "zoom control not available for this app."
    lines.append(f"- Text zoom: {zoom}")

    lines.append(f"- Relaxed reading: {_num(f.relaxed_min_now)} min at {_num(L.relaxed_cm)} cm or more without "
                 f"squinting (limit {_num(L.relaxed_min)} min), Far Point zoom {f.zoom_step:+d}: "
                 + ("text can go back one step." if text_can_go_back(f, L) else "no change needed."))

    if squint_despite_zoom(f):
        lines.append(f"- Squint despite zoom: squinting for {_num(f.squinting_s)} s at Far Point zoom "
                     f"{f.zoom_step:+d} (ask after 60 s at +2 or more): yes.")
    else:
        lines.append("- Squint despite zoom (ask after 60 s of squinting at Far Point zoom +2 or more): no.")

    lines.append(f"- Activity: {f.activity}.")
    if f.local_time:
        lines.append(f"- Local time: {f.local_time} ({part_of_day(f.local_time)}).")
    if prof.conditions:
        lines.append(f"- Profile (user's own words): {'; '.join(prof.conditions)}.")
    return "\n".join(lines)


def strain(f: Facts, L: Limits) -> dict:
    """Contract `strain`, counted in code (the spike showed the model at chance on it)."""
    signs = sum([bool(f.squinting), too_close(f, L), break_due(f, L), low_blink(f, L)])
    level = STRAIN_LEVELS[min(signs, 2)]
    return {
        "level": level,
        "expected": float(min(signs, 2)),
        "probs": {k: (1.0 if k == level else 0.0) for k in STRAIN_LEVELS},
        "signs": signs,
    }
