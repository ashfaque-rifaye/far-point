"""Reference predicates for the default doctrine, one per tool.

Used ONLY by the fake Decider (tests and the offline demo), eval labels and tests. The
live loop never uses them to decide: the Decider does.
"""
from __future__ import annotations

from collections.abc import Callable

from .doctrine import Limits
from .facts import Facts, break_due, relaxed_long_enough, squint_despite_zoom, too_close

Predicate = Callable[[Facts, Limits], bool]

PREDICATES: dict[str, Predicate] = {
    "enlarge_text": lambda f, L: too_close(f, L) and f.zoom_available,
    "glasses_reminder": lambda f, L: f.glasses_prescribed == "yes" and f.glasses_off_signs,
    "dark_mode": lambda f, L: f.room == "dark" and f.theme == "light",
    "dim_screen": lambda f, L: (f.room == "dark" and f.theme == "dark" and f.brightness_pct is not None
                                and f.brightness_pct >= L.dim_pct_high),
    "brighten_screen": lambda f, L: (f.room == "bright" and f.brightness_pct is not None
                                     and f.brightness_pct <= L.bright_pct_low),
    "far_look_break": lambda f, L: break_due(f, L),
    "reduce_text": lambda f, L: f.zoom_step > 0 and relaxed_long_enough(f, L),
    "ask_user": lambda f, L: squint_despite_zoom(f),
    "reset": lambda f, L: False,
}
