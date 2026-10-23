"""SignalTracker: turns per-frame readings into the facts the rules need.

Fed by the live camera source or by a replay trace; both go through `update()`. Every
timer integrates the time between updates (`dt`), so a replay at any speed gives the same
facts as live at 1x. Numbers only: no frames reach this module.
"""
from __future__ import annotations

import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .doctrine import Limits
from .facts import Facts

BLINK_ENTER = 0.6  # eye opening below 0.6 x baseline starts a blink
BLINK_EXIT = 0.7  # back above 0.7 x baseline ends it
BLINK_MAX_S = 1.0  # longer closures are not blinks
LOOK_YAW_DEG = 25.0
LOOK_PITCH_DEG = 20.0
UNDER30_CM = 30.0  # contract: "seconds closer than 30 cm today" (fixed, not a knob)
FACE_LOST_S = 1.0
USUAL_WINDOW_S = 30 * 60
USUAL_MIN_SAMPLES = 30
VISION_FAR_P = 0.65  # vision mode: P(looking far away) at which the gaze counts as away
VISION_FRESH_S = 5.0


@dataclass
class SensorSample:
    face: bool
    distance_cm: float | None = None
    ear: float | None = None
    squint_ratio: float | None = None
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    luma: float | None = None


def ambient_bucket(luma: float | None) -> str:
    if luma is None:
        return "normal"
    if luma < 50:
        return "dark"
    if luma < 90:
        return "dim"
    if luma < 170:
        return "normal"
    return "bright"


def distance_band(d: float | None) -> str | None:
    if d is None:
        return None
    if d < 30:
        return "too_close"
    if d < 40:
        return "close"
    if d < 80:
        return "healthy"
    return "far"


class SignalTracker:
    def __init__(self, limits: Limits | None = None, clock=time.time):
        self.limits = limits or Limits()
        self.clock = clock
        self._lock = threading.RLock()
        self._t: float | None = None
        self._day: str | None = None
        self._dist = deque(maxlen=5)
        self._ratio = deque(maxlen=5)
        self.face = False
        self._no_face_s = 0.0
        self.distance_cm: float | None = None
        self.squint_ratio: float | None = None
        self.raw_ratio: float | None = None
        self.yaw: float | None = None
        self.pitch: float | None = None
        self._luma: float | None = None
        self.under_near_s = 0.0
        self.bout_s = 0.0
        self._away_s = 0.0
        self.longest_bout_s = 0.0
        self.under30_today_s = 0.0
        self._below_s = 0.0
        self.squinting = False
        self.squint_episodes = 0
        self._in_blink = False
        self._blink_s = 0.0
        self._blinks: deque[float] = deque()
        self._blink_obs_s = 0.0
        self._usual: deque[tuple[float, float]] = deque()
        self._usual_seed: float | None = None
        self._last_usual_t: float | None = None
        self.relaxed_s = 0.0
        self.glasses_off_s = 0.0
        self.context: dict = {}
        self._vision: tuple[float, float | None] | None = None
        self._vision_glasses: tuple[float, bool | None] | None = None

    # ---- configuration -----------------------------------------------------------
    def set_limits(self, limits: Limits) -> None:
        with self._lock:
            self.limits = limits

    def seed_bout(self, seconds: float) -> None:
        with self._lock:
            self.bout_s = float(seconds)
            self.longest_bout_s = max(self.longest_bout_s, self.bout_s)

    def seed_usual_distance(self, cm: float) -> None:
        with self._lock:
            self._usual_seed = float(cm)

    def reset_bout(self) -> None:
        """Called after a verified far-look break."""
        with self._lock:
            self.bout_s = 0.0
            self._away_s = 0.0

    # ---- update ------------------------------------------------------------------
    def update(self, t: float, sample: SensorSample | None, context: dict | None = None) -> None:
        with self._lock:
            dt = 0.0 if self._t is None else max(0.0, min(1.0, t - self._t))
            self._t = t
            self._rollover(t)
            if context is not None:
                self.context = dict(context)
            L = self.limits
            if sample is not None and sample.luma is not None:
                self._luma = sample.luma if self._luma is None else 0.8 * self._luma + 0.2 * sample.luma

            has_face = bool(sample and sample.face and sample.distance_cm is not None)
            if has_face:
                self._no_face_s = 0.0
                self.face = True
                self._dist.append(float(sample.distance_cm))
                self.distance_cm = statistics.median(self._dist)
                if sample.squint_ratio is not None:
                    self.raw_ratio = float(sample.squint_ratio)
                    self._ratio.append(self.raw_ratio)
                    self.squint_ratio = statistics.median(self._ratio)
                self.yaw = sample.yaw_deg
                self.pitch = sample.pitch_deg
            else:
                self._no_face_s += dt
                if self._no_face_s >= FACE_LOST_S:
                    self.face = False
                    self.distance_cm = None
                    self._dist.clear()
                    self._ratio.clear()
                    self.yaw = self.pitch = None

            d = self.distance_cm if self.face else None
            # Continuous time closer than near_cm.
            self.under_near_s = self.under_near_s + dt if (d is not None and d < L.near_cm) else 0.0
            if d is not None and d < UNDER30_CM:
                self.under30_today_s += dt
            # Clouclip bout: time closer than bout_cm with the face present; resets after
            # bout_reset_s away or far.
            if d is not None and d < L.bout_cm:
                self.bout_s += dt
                self._away_s = 0.0
            else:
                self._away_s += dt
                if self._away_s >= L.bout_reset_s:
                    self.bout_s = 0.0
            self.longest_bout_s = max(self.longest_bout_s, self.bout_s)

            # Squint, debounced.
            r = self.squint_ratio if self.face else None
            if r is not None and r < L.squint_ratio:
                self._below_s += dt
                was = self.squinting
                self.squinting = self._below_s >= L.squint_s
                if self.squinting and not was:
                    self.squint_episodes += 1
            else:
                self._below_s = 0.0
                self.squinting = False

            # Blinks on the raw (unsmoothed) eye opening.
            if has_face and self.raw_ratio is not None:
                self._blink_obs_s = min(60.0, self._blink_obs_s + dt)
                if not self._in_blink and self.raw_ratio < BLINK_ENTER:
                    self._in_blink, self._blink_s = True, 0.0
                elif self._in_blink:
                    self._blink_s += dt
                    if self.raw_ratio > BLINK_EXIT:
                        if self._blink_s <= BLINK_MAX_S:
                            self._blinks.append(t)
                        self._in_blink = False
            elif self._no_face_s > 5.0:
                self._blinks.clear()
                self._blink_obs_s = 0.0
                self._in_blink = False
            while self._blinks and t - self._blinks[0] > 60.0:
                self._blinks.popleft()

            # Usual distance: rolling median of relaxed samples (1 Hz, 30 min).
            relaxed_now = d is not None and not self.squinting and d >= L.near_cm
            if relaxed_now and (self._last_usual_t is None or t - self._last_usual_t >= 1.0):
                self._usual.append((t, d))
                self._last_usual_t = t
            while self._usual and t - self._usual[0][0] > USUAL_WINDOW_S:
                self._usual.popleft()

            # Relaxed reading: continuous time at >= relaxed_cm without squinting.
            if d is not None and d >= L.relaxed_cm and not self.squinting:
                self.relaxed_s += dt
            else:
                self.relaxed_s = 0.0
            if self.face and (self._vision_glasses_off() if self._vision_glasses is not None else self.glasses_off_signs):
                self.glasses_off_s += dt

    def _rollover(self, t: float) -> None:
        day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        if self._day is not None and day != self._day:
            self.under30_today_s = 0.0
            self.longest_bout_s = self.bout_s
            self.squint_episodes = 0
            self.glasses_off_s = 0.0
        self._day = day

    # ---- derived -----------------------------------------------------------------
    @property
    def usual_distance_cm(self) -> float | None:
        if len(self._usual) >= USUAL_MIN_SAMPLES:
            return statistics.median(d for _, d in self._usual)
        return self._usual_seed

    @property
    def squinting_s(self) -> float:
        return self._below_s if self.squinting else 0.0

    @property
    def blink_per_min(self) -> float | None:
        if self._blink_obs_s < 30.0:
            return None
        return len(self._blinks) * 60.0 / self._blink_obs_s

    def set_vision(self, t: float, looking_far_p: float | None, glasses_on: bool | None = None) -> None:
        """Vision mode only: the local Decider's answers for the latest webcam frame."""
        with self._lock:
            self._vision = (float(t), looking_far_p)
            self._vision_glasses = (float(t), glasses_on)

    def _vision_glasses_off(self) -> bool:
        g = self._vision_glasses
        return g is not None and g[1] is False and self._t is not None and self._t - g[0] <= VISION_FRESH_S * 2

    @property
    def looking_at_screen(self) -> bool | None:
        if not self.face:
            return None
        v = self._vision
        if (v is not None and v[1] is not None and v[1] >= VISION_FAR_P and self._t is not None
                and self._t - v[0] <= VISION_FRESH_S):
            return False  # the camera image says the gaze is far away, whatever the head angle
        if self.yaw is None or self.pitch is None:
            return True
        return abs(self.yaw) < LOOK_YAW_DEG and abs(self.pitch) < LOOK_PITCH_DEG

    @property
    def glasses_off_signs(self) -> bool:
        u = self.usual_distance_cm
        d = self.distance_cm if self.face else None
        return u is not None and d is not None and self.squinting and d <= u - self.limits.lean_in_cm

    @property
    def ambient(self) -> str:
        return ambient_bucket(self._luma)

    def snapshot(self) -> Facts:
        with self._lock:
            c = self.context
            return Facts(
                face=self.face,
                distance_cm=round(self.distance_cm, 1) if self.face and self.distance_cm is not None else None,
                under_near_s=round(self.under_near_s, 1),
                bout_min_now=round(self.bout_s / 60.0, 2),
                squinting=self.squinting,
                squinting_s=round(self.squinting_s, 1),
                squint_ratio=round(self.squint_ratio, 3) if self.face and self.squint_ratio is not None else None,
                blink_per_min=None if self.blink_per_min is None else round(self.blink_per_min, 1),
                looking_at_screen=self.looking_at_screen,
                usual_distance_cm=None if self.usual_distance_cm is None else round(self.usual_distance_cm, 1),
                glasses_off_signs=self.glasses_off_signs,
                room=self.ambient,
                app_name=c.get("app_name", ""),
                app_category=c.get("category", "other"),
                relaxed_min_now=round(self.relaxed_s / 60.0, 2),
                activity=c.get("activity", "idle (no foreground window information)"),
                interrupt_ok_hint=c.get("interrupt_ok_hint"),
            )

    def signals_payload(self, zoom_step: int = 0, glasses_on: bool | None = None) -> dict:
        with self._lock:
            d = round(self.distance_cm, 1) if self.face and self.distance_cm is not None else None
            bpm = self.blink_per_min
            if bpm is None and self._blink_obs_s > 0:
                bpm = len(self._blinks) * 60.0 / max(self._blink_obs_s, 30.0)
            return {
                "face": self.face,
                "distance_cm": d,
                "distance_band": distance_band(d),
                "squint": round(self.squint_ratio, 3) if self.squint_ratio is not None else 1.0,
                "squinting": self.squinting,
                "blink_per_min": round(bpm or 0.0, 1),
                "looking_at_screen": self.looking_at_screen,
                "ambient": self.ambient,
                "glasses_on": glasses_on,
                "bout_s": round(self.bout_s, 1),
                "under30_today_s": round(self.under30_today_s, 1),
                "app": {
                    "name": self.context.get("app_name", "") or "unknown",
                    "category": self.context.get("category", "other"),
                    "zoom_step": int(zoom_step),
                },
            }

    def stats_view(self) -> dict:
        with self._lock:
            return {
                "under30_min": round(self.under30_today_s / 60.0, 2),
                "longest_bout_min": round(self.longest_bout_s / 60.0, 2),
                "squint_episodes": self.squint_episodes,
                "glasses_off_min": round(self.glasses_off_s / 60.0, 2),
            }
