"""Facts the loop measured, rendered in words with the comparisons already done.

The Decider never does arithmetic: every line ends with the verdict the rule criteria
quote ("too close", "break is due", "mismatch", ...). Strain is counted in code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .doctrine import Doctrine, Limits

ROOM_WORDS = {"dark": "dark", "dim": "dim", "normal": "normal indoor light", "bright": "bright"}
STRAIN_LEVELS = ("relaxed", "mild", "strong")


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


def brightness_verdict(f: Facts, L: Limits) -> str:
    if f.brightness_pct is None:
        return "not adjustable"
    if f.room == "dark" and f.brightness_pct >= L.dim_pct_high:
        return "high for a dark room"
    if f.room == "bright" and f.brightness_pct <= L.bright_pct_low:
        return "low for a bright room"
    return "suits the room"


def _num(x: float) -> str:
    return f"{x:.0f}"


def render_state(f: Facts, doctrine: Doctrine) -> str:
    L = doctrine.limits
    prof = doctrine.profile
    lines = ["Measured now (code computed every number and comparison):"]

    if not f.face or f.distance_cm is None:
        lines.append("- Viewing distance: no face visible.")
    elif too_close(f, L):
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm, closer than {_num(L.near_cm)} cm for "
                     f"{_num(f.under_near_s)} s (limit {_num(L.near_s)} s): too close.")
    elif f.distance_cm < L.near_cm:
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm, closer than {_num(L.near_cm)} cm for "
                     f"{_num(f.under_near_s)} s (too close after {_num(L.near_s)} s): distance OK for now.")
    else:
        lines.append(f"- Viewing distance: {_num(f.distance_cm)} cm (too close means under {_num(L.near_cm)} cm "
                     f"for over {_num(L.near_s)} s): distance OK.")

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

    lines.append(f"- Glasses prescribed for screen work: {prof.glasses_for_screen}.")
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
    lines.append(f"- Glasses: {worn}; {signs}.")

    lines.append(f"- Room light: {f.room} (estimated from camera brightness).")
    if f.room == "dark" and f.theme == "light":
        lines.append("- Theme: light, in a dark room: mismatch.")
    else:
        lines.append(f"- Theme: {f.theme}: suits the room.")

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
                 f"squinting (limit {_num(L.relaxed_min)} min): "
                 + ("relaxed long enough." if relaxed_long_enough(f, L) else "not long enough yet."))

    if squint_despite_zoom(f):
        lines.append(f"- Squint despite zoom: squinting for {_num(f.squinting_s)} s at Far Point zoom "
                     f"{f.zoom_step:+d} (ask after 60 s at +2 or more): yes.")
    else:
        lines.append("- Squint despite zoom (ask after 60 s of squinting at Far Point zoom +2 or more): no.")

    lines.append(f"- Activity: {f.activity}.")
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
