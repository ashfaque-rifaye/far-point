"""Closed-loop verification: did the adaptation change what the camera measures?

Outcomes (engineering choices, not clinical thresholds):
- worked: distance went from under 40 cm to 40 cm or more, or eye opening rose by >= 0.10;
- worse: distance fell by >= 3 cm AND eye opening fell by >= 0.05;
- n/a: no face before or after;
- no_change: anything else.
Breaks are verified by the break outcome itself (verified -> worked).
"""
from __future__ import annotations

import threading

WORKED_CM = 40.0
SQUINT_GAIN = 0.10
WORSE_CM = 3.0
WORSE_SQUINT = 0.05
BREAK_OUTCOME = {"verified": "worked", "abandoned": "no_change", "skipped": "n/a"}


def judge(before: dict, after: dict) -> str:
    bd, ad = before.get("distance_cm"), after.get("distance_cm")
    bs, as_ = before.get("squint"), after.get("squint")
    if ad is None or (bd is None and bs is None):
        return "n/a"
    if bd is not None and bd < WORKED_CM <= ad:
        return "worked"
    if bs is not None and as_ is not None and as_ - bs >= SQUINT_GAIN:
        return "worked"
    if (bd is not None and bs is not None and as_ is not None
            and bd - ad >= WORSE_CM and bs - as_ >= WORSE_SQUINT):
        return "worse"
    return "no_change"


class Verifier:
    def __init__(self, bus, tracker, stats, prefs, clock, window_s: float = 30.0):
        self.bus = bus
        self.tracker = tracker
        self.stats = stats
        self.prefs = prefs
        self.clock = clock
        self.window_s = window_s
        self._watches: list[dict] = []
        self._lock = threading.Lock()
        self.results: list[dict] = []

    def measure(self) -> dict:
        tr = self.tracker
        return {"distance_cm": round(tr.distance_cm, 1) if tr.face and tr.distance_cm is not None else None,
                "squint": round(tr.squint_ratio, 3) if tr.face and tr.squint_ratio is not None else None}

    def watch(self, action_id: str, tool: str, before: dict, category: str, window_s: float | None = None) -> None:
        w = window_s or self.window_s
        with self._lock:
            self._watches.append({"action_id": action_id, "tool": tool, "before": dict(before), "category": category,
                                  "due": self.clock() + w, "window_s": w})

    def pending(self) -> int:
        with self._lock:
            return len(self._watches)

    def on_time(self, t: float) -> None:
        with self._lock:
            due = [w for w in self._watches if t >= w["due"]]
            self._watches = [w for w in self._watches if t < w["due"]]
        for w in due:
            after = self.measure()
            self._emit(w["action_id"], w["tool"], w["category"], judge(w["before"], after), w["before"], after,
                       w["window_s"])

    def on_break_outcome(self, action_id: str | None, phase: str, before: dict, after: dict, duration_s: float,
                         category: str = "other") -> None:
        if not action_id:
            return
        self._emit(action_id, "far_look_break", category, BREAK_OUTCOME.get(phase, "n/a"), before, after,
                   round(duration_s, 1))

    def _emit(self, action_id, tool, category, outcome, before, after, window_s) -> None:
        data = {"action_id": action_id, "outcome": outcome, "before": before, "after": after,
                "window_s": window_s}
        self.bus.publish("verification", data)
        if outcome == "worked":
            self.stats.inc("adaptations_worked")
        self.prefs.record(tool, category, outcome)
        self.results.append({**data, "tool": tool})
