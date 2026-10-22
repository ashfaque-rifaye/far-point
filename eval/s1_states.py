"""Synthetic labeled states for spike S1 (text decisions).

Code computes every number and comparison and renders the result in words, so the
Decider never does arithmetic. Labels come from the doctrine rules in `label()`, not
from the model. Generation is deterministic for a given seed.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

ACTIONS = (
    "none", "enlarge_text", "reduce_text", "dim_screen", "brighten_screen",
    "dark_mode", "far_look_break", "glasses_reminder", "ask_user",
)
# Doctrine priority when several actions apply (first wins).
PRIORITY = (
    "ask_user", "glasses_reminder", "enlarge_text", "dark_mode", "dim_screen",
    "brighten_screen", "far_look_break", "reduce_text",
)
STRAIN_LEVELS = ("relaxed", "mild", "strong")

MIN_DISTANCE_CM = 40
MIN_TEXT_PX = 14
LARGE_TEXT_PX = 18
BREAK_DUE_MIN = 20
LOW_BLINK_PER_MIN = 10

PROFILES = {
    "myopia": dict(
        condition="myopia (short-sighted), -2.50 D both eyes",
        glasses_prescribed=True,
        glasses_note="distance glasses, prescribed for screen work",
    ),
    "presbyopia": dict(
        condition="presbyopia with mild hyperopia, +1.50 D reading add",
        glasses_prescribed=True,
        glasses_note="reading glasses, prescribed for screen work",
    ),
    "none": dict(
        condition="no diagnosed refractive error",
        glasses_prescribed=False,
        glasses_note="no glasses prescribed",
    ),
}

# (description, interrupt_ok)
ACTIVITIES = (
    ("idle for 30 s after saving a file (foreground: VS Code)", True),
    ("just switched from the editor to the browser", True),
    ("between tasks: closed a document 10 s ago, no input since", True),
    ("idle for 45 s with a web page open (foreground: Edge)", True),
    ("in a video call (foreground: Microsoft Teams, microphone active)", False),
    ("presenting: screen sharing in Zoom", False),
    ("typing in a burst, last keystroke 0.4 s ago (foreground: Word)", False),
    ("watching a fullscreen video (foreground: YouTube)", False),
)


@dataclass
class Facts:
    profile: str
    distance_cm: int
    squinting: bool
    squint_seconds: int
    eye_opening_pct: int
    blink_per_min: int
    glasses_on: bool
    text_px: int
    zoom_pct: int
    text_enlarged_earlier: bool
    relaxed_minutes: int
    room: str  # dark | normal | bright
    room_lux: int
    screen_brightness_pct: int
    theme: str  # light | dark
    near_work_min: int
    activity: str
    interrupt_ok: bool

    # ---- derived comparisons (code does the arithmetic) ----
    @property
    def glasses_prescribed(self) -> bool:
        return PROFILES[self.profile]["glasses_prescribed"]

    @property
    def too_close(self) -> bool:
        return self.distance_cm < MIN_DISTANCE_CM

    @property
    def text_small(self) -> bool:
        return self.text_px < MIN_TEXT_PX

    @property
    def text_large(self) -> bool:
        return self.text_px >= LARGE_TEXT_PX

    @property
    def screen_vs_room(self) -> str:
        if self.room == "dark" and self.screen_brightness_pct >= 70:
            return "much brighter than the room"
        if self.room == "bright" and self.screen_brightness_pct <= 30:
            return "much dimmer than the room"
        return "balanced with the room"

    @property
    def break_due(self) -> bool:
        return self.near_work_min >= BREAK_DUE_MIN

    @property
    def low_blink(self) -> bool:
        return self.blink_per_min < LOW_BLINK_PER_MIN


def triggers(f: Facts) -> list[str]:
    """Every doctrine action whose condition holds, in priority order."""
    hits = {
        "ask_user": f.squinting and f.text_large and (f.glasses_on or not f.glasses_prescribed),
        "glasses_reminder": f.glasses_prescribed and not f.glasses_on,
        "enlarge_text": f.text_small and (f.squinting or f.too_close),
        "dark_mode": f.room == "dark" and f.theme == "light",
        "dim_screen": f.room == "dark" and f.theme == "dark" and f.screen_vs_room == "much brighter than the room",
        "brighten_screen": f.screen_vs_room == "much dimmer than the room",
        "far_look_break": f.break_due,
        "reduce_text": f.text_enlarged_earlier and not f.squinting and not f.too_close and f.relaxed_minutes >= 10,
    }
    return [a for a in PRIORITY if hits[a]]


def label(f: Facts) -> dict:
    t = triggers(f)
    signs = sum([f.squinting, f.too_close, f.break_due, f.low_blink])
    return {
        "next_action": t[0] if t else "none",
        "strain": STRAIN_LEVELS[min(signs, 2)],
        "interrupt_ok": f.interrupt_ok,
    }


def doctrine_text(profile: str) -> str:
    p = PROFILES[profile]
    return "\n".join([
        f"User: {p['condition']}; {p['glasses_note']}.",
        "Doctrine:",
        f"- Keep the eyes at least {MIN_DISTANCE_CM} cm from the screen.",
        f"- Comfortable text is at least {MIN_TEXT_PX} px. If text is smaller and the user squints or sits too close, enlarge the text.",
        "- If text was enlarged earlier and the user has been relaxed at a comfortable distance for 10 minutes or more, return the text to its default size.",
        f"- 20-20-20 rule: after {BREAK_DUE_MIN} minutes of continuous near work, take a far-look break (look 6 m away for 20 s).",
        "- If glasses are prescribed for screen work, they should be worn.",
        "- Dark room with a light theme: switch to dark mode. Dark room, dark theme already on, screen much brighter than the room: dim the screen. Bright room with the screen much dimmer than the room: brighten the screen.",
        "- If the user keeps squinting even with glasses on (or none prescribed) and text already large, ask the user how their eyes feel.",
        "- Priority when several apply: " + ", ".join(PRIORITY) + ". If nothing applies: none.",
    ])


def render(f: Facts) -> str:
    p = PROFILES[f.profile]
    if f.too_close:
        dist = f"{f.distance_cm} cm, {MIN_DISTANCE_CM - f.distance_cm} cm closer than the {MIN_DISTANCE_CM} cm minimum: too close"
    else:
        dist = f"{f.distance_cm} cm (minimum {MIN_DISTANCE_CM} cm): OK"
    eyes = (
        f"squinting for {f.squint_seconds} s (eye opening {f.eye_opening_pct}% of baseline)"
        if f.squinting else f"not squinting (eye opening {f.eye_opening_pct}% of baseline)"
    )
    blink = f"{f.blink_per_min} per minute (normal is {LOW_BLINK_PER_MIN} or more): " + ("low" if f.low_blink else "normal")
    if p["glasses_prescribed"]:
        glasses = ("on" if f.glasses_on else "off") + " (glasses are prescribed for screen work)"
    else:
        glasses = ("on" if f.glasses_on else "off") + " (no glasses prescribed)"
    if f.text_small:
        text = f"{f.text_px} px at {f.zoom_pct}% zoom, below the {MIN_TEXT_PX} px comfortable minimum: small"
    elif f.text_large:
        text = f"{f.text_px} px at {f.zoom_pct}% zoom: large"
    else:
        text = f"{f.text_px} px at {f.zoom_pct}% zoom (comfortable minimum {MIN_TEXT_PX} px): OK"
    enlarged = (
        f"yes; relaxed at a comfortable distance for the last {f.relaxed_minutes} min"
        if f.text_enlarged_earlier else "no"
    )
    room = {"dark": "dark", "normal": "normal office light", "bright": "bright daylight"}[f.room]
    if f.break_due:
        work = f"{f.near_work_min} min since the last far-look break (break due at {BREAK_DUE_MIN} min): break is due"
    else:
        work = f"{f.near_work_min} min since the last far-look break (break due at {BREAK_DUE_MIN} min): not due yet"
    return "\n".join([
        doctrine_text(f.profile),
        "",
        "Measured now:",
        f"- Viewing distance: {dist}.",
        f"- Eyes: {eyes}.",
        f"- Blink rate: {blink}.",
        f"- Glasses: {glasses}.",
        f"- Text size: {text}.",
        f"- Text was enlarged earlier: {enlarged}.",
        f"- Room light: {room} ({f.room_lux} lux). Screen brightness {f.screen_brightness_pct}%: {f.screen_vs_room}.",
        f"- Theme: {f.theme}.",
        f"- Continuous near work: {work}.",
        f"- Activity: {f.activity}.",
    ])


# ---- generation ----------------------------------------------------------------


def _neutral(rng: random.Random) -> Facts:
    profile = rng.choice(list(PROFILES))
    activity, ok = rng.choice(ACTIVITIES)
    room = rng.choice(["normal", "normal", "bright", "dark"])
    theme = rng.choice(["light", "dark"])
    if room == "dark":
        theme, bright = "dark", rng.randint(25, 50)
    elif room == "bright":
        bright = rng.randint(60, 95)
    else:
        bright = rng.randint(40, 80)
    lux = {"dark": rng.randint(5, 40), "normal": rng.randint(250, 450), "bright": rng.randint(900, 2500)}[room]
    text_px = rng.choice([14, 15, 16, 16, 17])
    return Facts(
        profile=profile,
        distance_cm=rng.randint(45, 70),
        squinting=False,
        squint_seconds=0,
        eye_opening_pct=rng.randint(90, 104),
        blink_per_min=rng.randint(12, 20),
        glasses_on=PROFILES[profile]["glasses_prescribed"],
        text_px=text_px,
        zoom_pct=100,
        text_enlarged_earlier=False,
        relaxed_minutes=0,
        room=room,
        room_lux=lux,
        screen_brightness_pct=bright,
        theme=theme,
        near_work_min=rng.randint(2, 16),
        activity=activity,
        interrupt_ok=ok,
    )


def _squint(f: Facts, rng: random.Random) -> None:
    f.squinting = True
    f.squint_seconds = rng.randint(20, 120)
    f.eye_opening_pct = rng.randint(55, 72)


def _make(target: str, rng: random.Random, combo: bool) -> Facts:
    """A state whose label is `target`. `combo` adds a lower-priority trigger too."""
    for _ in range(500):
        f = _neutral(rng)
        if target == "glasses_reminder":
            f.profile = rng.choice(["myopia", "presbyopia"])
            f.glasses_on = False
        elif target == "enlarge_text":
            f.text_px = rng.choice([10, 11, 12, 13])
            f.zoom_pct = rng.choice([90, 100])
            if rng.random() < 0.5:
                _squint(f, rng)
            else:
                f.distance_cm = rng.randint(26, 38)
        elif target == "dark_mode":
            f.room, f.room_lux, f.theme = "dark", rng.randint(5, 40), "light"
            f.screen_brightness_pct = rng.randint(30, 100)
        elif target == "dim_screen":
            f.room, f.room_lux, f.theme = "dark", rng.randint(5, 40), "dark"
            f.screen_brightness_pct = rng.randint(75, 100)
        elif target == "brighten_screen":
            f.room, f.room_lux = "bright", rng.randint(900, 2500)
            f.screen_brightness_pct = rng.randint(10, 28)
        elif target == "far_look_break":
            f.near_work_min = rng.randint(20, 55)
        elif target == "reduce_text":
            f.text_enlarged_earlier = True
            f.text_px = rng.choice([20, 22, 24])
            f.zoom_pct = rng.choice([125, 150, 175])
            f.relaxed_minutes = rng.randint(10, 30)
        elif target == "ask_user":
            _squint(f, rng)
            f.text_px = rng.choice([18, 20, 22])
            f.zoom_pct = rng.choice([125, 150])
        if combo:
            lower = PRIORITY[PRIORITY.index(target) + 1:] if target in PRIORITY else ()
            if "far_look_break" in lower:
                f.near_work_min = rng.randint(20, 45)
            elif target == "far_look_break":
                f.text_enlarged_earlier = True
                f.text_px, f.zoom_pct = 20, 150
                f.relaxed_minutes = rng.randint(10, 25)
        # Distractor: low blink rate changes strain but no action.
        if rng.random() < 0.3:
            f.blink_per_min = rng.randint(5, 9)
        if label(f)["next_action"] == target:
            return f
    raise RuntimeError(f"could not generate a state for {target}")


def generate(seed: int = 1, per_label: int = 8) -> list[dict]:
    rng = random.Random(seed)
    items = []
    for target in ACTIONS:
        for i in range(per_label):
            # Two of every eight states carry a second, lower-priority trigger.
            f = _make(target, rng, combo=(i % 4 == 3 and target not in ("none", "reduce_text")))
            items.append({"facts": asdict(f), "state": render(f), "labels": label(f), "triggers": triggers(f)})
    rng.shuffle(items)
    for i, it in enumerate(items):
        it["id"] = f"s{seed}-{i:03d}"
    return items


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    items = generate(seed)
    print(items[0]["state"])
    print(items[0]["labels"], items[0]["triggers"])
    from collections import Counter
    print(Counter(it["labels"]["next_action"] for it in items))
    print(Counter(len(it["triggers"]) for it in items))
