"""20-20-20 far-look breaks, verified by the camera rather than a timer.

`looking_away_s` grows only while the tracker says the user is not looking at the screen
(head turned) or no face is visible (walked away; counted and noted as `face_absent_s`).
Driven by `on_time(t)`, so it runs at any replay speed and never blocks the reflex loop.
"""
from __future__ import annotations

import itertools
import threading
from collections.abc import Callable

TIMEOUT_S = 60.0
TICK_S = 1.0


class BreakManager:
    def __init__(self, bus, overlay, tracker, stats, clock, on_outcome: Callable[..., None] | None = None):
        self.bus = bus
        self.overlay = overlay
        self.tracker = tracker
        self.stats = stats
        self.clock = clock
        self.on_outcome = on_outcome
        self.active: dict | None = None
        self.streak = 0
        self._ids = itertools.count(1)
        self._lock = threading.RLock()

    def _measure(self) -> dict:
        tr = self.tracker
        return {"distance_cm": round(tr.distance_cm, 1) if tr.face and tr.distance_cm is not None else None,
                "squint": round(tr.squint_ratio, 3) if tr.face and tr.squint_ratio is not None else None}

    def _emit(self, phase: str) -> None:
        a = self.active
        self.bus.publish("break", {
            "id": a["id"], "phase": phase, "target_s": a["target_s"],
            "looking_away_s": round(a["looking_away_s"], 1), "streak": self.streak,
            "face_absent_s": round(a["face_absent_s"], 1),
        })

    def is_active(self) -> bool:
        with self._lock:
            return self.active is not None

    def start(self, target_s: float = 20, action_id: str | None = None, category: str = "other") -> str:
        with self._lock:
            if self.active is not None:
                return self.active["id"]
            t = self.clock()
            bid = f"b_{next(self._ids):06d}"
            self.active = {"id": bid, "target_s": float(target_s), "looking_away_s": 0.0, "face_absent_s": 0.0,
                           "t_start": t, "last_t": t, "last_tick": t, "action_id": action_id,
                           "before": self._measure(), "category": category}
            self.stats.inc("breaks_offered")
            self._emit("offered")
            self._emit("started")
        self.overlay.show_break(target_s, on_skip=lambda: self.skip(bid))
        return bid

    def skip(self, bid: str) -> bool:
        with self._lock:
            if self.active is None or self.active["id"] != bid:
                return False
            self._finish("skipped")
            return True

    def on_time(self, t: float) -> None:
        with self._lock:
            a = self.active
            if a is None:
                return
            dt = max(0.0, min(1.0, t - a["last_t"]))
            a["last_t"] = t
            looking = self.tracker.looking_at_screen
            if looking is None:
                a["looking_away_s"] += dt
                a["face_absent_s"] += dt
            elif looking is False:
                a["looking_away_s"] += dt
            if a["looking_away_s"] >= a["target_s"]:
                a["looking_away_s"] = a["target_s"]
                self._finish("verified")
            elif t - a["t_start"] >= TIMEOUT_S:
                self._finish("abandoned")
            elif t - a["last_tick"] >= TICK_S:
                a["last_tick"] = t
                self._emit("tick")
                self.overlay.update(a["looking_away_s"])

    def _finish(self, phase: str) -> None:
        a = self.active
        if phase == "verified":
            self.streak += 1
            self.stats.inc("breaks_verified")
            self.tracker.reset_bout()
        else:
            self.streak = 0
        self.stats.set("streak", self.streak)
        self._emit(phase)
        self.active = None
        self.overlay.close()
        if self.on_outcome is not None:
            self.on_outcome(action_id=a["action_id"], phase=phase, before=a["before"], after=self._measure(),
                            duration_s=a["last_t"] - a["t_start"], category=a["category"])
