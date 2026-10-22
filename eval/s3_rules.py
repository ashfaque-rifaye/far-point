"""S3: the S1 doctrine as 8 per-rule nouls, plus the renderers (see eval/PREREGISTRATION.md, Phase 2).

`RULES_NEW` pairs with `render_s3` (Far Point's Phase 2 style: code folds every condition a
rule combines into one line ending in a verdict phrase). `RULES_OLD` pairs with the original
`s1_states.render` text (ablation); its criteria quote the old lines, as the S1 v2 options did.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from s1_states import (  # noqa: E402
    BREAK_DUE_MIN,
    LARGE_TEXT_PX,
    LOW_BLINK_PER_MIN,
    MIN_DISTANCE_CM,
    MIN_TEXT_PX,
    PRIORITY,
    PROFILES,
    Facts,
)

from patterns.reflex_gate import Rule  # noqa: E402


def _r(n, tool, text, t, f):
    return Rule(n, tool, text, t, f)


RULES_NEW = [
    _r(1, "ask_user", "The Squint check line says asking needed.",
       "the Squint check line says 'asking needed'", "the Squint check line says 'no asking needed'"),
    _r(2, "glasses_reminder", "The Glasses line says glasses reminder needed.",
       "the Glasses line says 'glasses reminder needed'", "the Glasses line says 'no reminder needed'"),
    _r(3, "enlarge_text", "The Text size line says enlarging needed.",
       "the Text size line says 'enlarging needed'", "the Text size line says 'no enlarging needed'"),
    _r(4, "dark_mode", "The Theme line says dark mode needed.",
       "the Theme line says 'mismatch, dark mode needed'", "the Theme line says 'no change needed'"),
    _r(5, "dim_screen", "The Screen brightness line says dimming needed.",
       "the Screen brightness line says 'dimming needed'",
       "the Screen brightness line says 'no change needed' or 'brightening needed'"),
    _r(6, "brighten_screen", "The Screen brightness line says brightening needed.",
       "the Screen brightness line says 'brightening needed'",
       "the Screen brightness line says 'no change needed' or 'dimming needed'"),
    _r(7, "far_look_break", "The Continuous near work line says break is due.",
       "the Continuous near work line ends with 'break is due'",
       "the Continuous near work line ends with 'not due yet'"),
    _r(8, "reduce_text", "The Text enlarged earlier line says text can go back to default.",
       "the Text enlarged earlier line says 'text can go back to default'",
       "the Text enlarged earlier line says 'no change needed'"),
]

RULES_OLD = [
    _r(1, "ask_user", "The user keeps squinting with large text, and glasses are on or none are prescribed.",
       "Eyes: squinting, AND Text size: large, AND glasses are on or none are prescribed",
       "Eyes: not squinting, OR Text size is not large, OR glasses are off while prescribed"),
    _r(2, "glasses_reminder", "Glasses are prescribed for screen work and the user is not wearing them.",
       "Glasses: off, while glasses are prescribed for screen work",
       "Glasses: on, OR no glasses prescribed"),
    _r(3, "enlarge_text", "Text is small and the user is squinting or too close.",
       "Text size: small, AND (Eyes: squinting OR Viewing distance: too close)",
       "Text size is OK or large, OR (Eyes: not squinting AND Viewing distance: OK)"),
    _r(4, "dark_mode", "The room is dark and the theme is light.",
       "Room light: dark, AND Theme: light", "Room light is not dark, OR Theme: dark"),
    _r(5, "dim_screen", "The room is dark, the theme is dark, and the screen is much brighter than the room.",
       "Room light: dark, AND Theme: dark, AND the screen is much brighter than the room",
       "Room light is not dark, OR Theme: light, OR the screen is balanced with the room"),
    _r(6, "brighten_screen", "The screen is much dimmer than the room.",
       "the screen is much dimmer than the room", "the screen is balanced with or brighter than the room"),
    _r(7, "far_look_break", "Continuous near work says break is due.",
       "Continuous near work: break is due", "Continuous near work: not due yet"),
    _r(8, "reduce_text", "Text was enlarged earlier and the user has been relaxed for 10 minutes or more.",
       "Text was enlarged earlier: yes, and relaxed at a comfortable distance for 10 min or more, not squinting, "
       "not too close",
       "Text was enlarged earlier: no, OR relaxed for less than 10 min, OR squinting, OR too close"),
]

assert [r.tool for r in RULES_NEW] == list(PRIORITY) == [r.tool for r in RULES_OLD]


def reference(f: Facts) -> dict[str, bool]:
    """Per-rule truth, written out from the S1 doctrine (the test checks it equals s1_states.triggers)."""
    return {
        "ask_user": f.squinting and f.text_large and (f.glasses_on or not f.glasses_prescribed),
        "glasses_reminder": f.glasses_prescribed and not f.glasses_on,
        "enlarge_text": f.text_small and (f.squinting or f.too_close),
        "dark_mode": f.room == "dark" and f.theme == "light",
        "dim_screen": f.room == "dark" and f.theme == "dark" and f.screen_vs_room == "much brighter than the room",
        "brighten_screen": f.screen_vs_room == "much dimmer than the room",
        "far_look_break": f.break_due,
        "reduce_text": f.text_enlarged_earlier and not f.squinting and not f.too_close and f.relaxed_minutes >= 10,
    }


def render_s3(f: Facts) -> str:
    """S1 facts in Far Point's Phase 2 style: one verdict phrase per rule line, computed by code."""
    p = PROFILES[f.profile]
    ref = reference(f)
    dist = (f"{f.distance_cm} cm (minimum {MIN_DISTANCE_CM} cm): too close" if f.too_close
            else f"{f.distance_cm} cm (minimum {MIN_DISTANCE_CM} cm): OK")
    eyes = (f"squinting for {f.squint_seconds} s (eye opening {f.eye_opening_pct}% of baseline)" if f.squinting
            else f"not squinting (eye opening {f.eye_opening_pct}% of baseline)")
    blink = f"{f.blink_per_min} per minute (normal is {LOW_BLINK_PER_MIN} or more): " + ("low" if f.low_blink else "normal")
    presc = "prescribed for screen work" if p["glasses_prescribed"] else "no glasses prescribed"
    glasses = (f"{'on' if f.glasses_on else 'off'}; {presc}: "
               + ("glasses reminder needed" if ref["glasses_reminder"] else "no reminder needed"))
    size = "small" if f.text_small else ("large" if f.text_large else "OK")
    text = (f"{f.text_px} px at {f.zoom_pct}% zoom ({size}; minimum {MIN_TEXT_PX} px; enlarge when small and "
            "squinting or too close): " + ("enlarging needed" if ref["enlarge_text"] else "no enlarging needed"))
    ask = (f"squinting even with large text ({LARGE_TEXT_PX} px or more) and glasses on or none prescribed: "
           + ("asking needed" if ref["ask_user"] else "no asking needed"))
    room = {"dark": "dark", "normal": "normal office light", "bright": "bright daylight"}[f.room]
    theme = ("light, in a dark room: mismatch, dark mode needed" if ref["dark_mode"]
             else f"{f.theme}: no change needed")
    if ref["dim_screen"]:
        bright = f"{f.screen_brightness_pct}%, much brighter than the dark room (dark theme): dimming needed"
    elif ref["brighten_screen"]:
        bright = f"{f.screen_brightness_pct}%, much dimmer than the bright room: brightening needed"
    else:
        bright = f"{f.screen_brightness_pct}%: no change needed"
    work = (f"{f.near_work_min} min since the last far-look break (break due at {BREAK_DUE_MIN} min): "
            + ("break is due" if f.break_due else "not due yet"))
    if f.text_enlarged_earlier:
        enl = (f"yes; relaxed at a comfortable distance without squinting for {f.relaxed_minutes} min (10 min needed): "
               + ("text can go back to default" if ref["reduce_text"] else "no change needed"))
    else:
        enl = "no: no change needed"
    return "\n".join([
        f"User: {p['condition']}; {p['glasses_note']}.",
        "",
        "Measured now (code computed every number and comparison):",
        f"- Viewing distance: {dist}.",
        f"- Eyes: {eyes}.",
        f"- Blink rate: {blink}.",
        f"- Squint check: {ask}.",
        f"- Glasses: {glasses}.",
        f"- Text size: {text}.",
        f"- Room light: {room} ({f.room_lux} lux).",
        f"- Theme: {theme}.",
        f"- Screen brightness: {bright}.",
        f"- Continuous near work: {work}.",
        f"- Text enlarged earlier: {enl}.",
        f"- Activity: {f.activity}.",
    ])
