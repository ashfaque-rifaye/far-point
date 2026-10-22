"""Signal sources: the live webcam, or a replay trace of recorded numbers.

Both feed the same SignalTracker and call `on_time(t)` after every sample, so breaks,
verification and (in replay) the reflex loop run on the same clock as the data.
Frames never leave LiveSource: each one is reduced to numbers and dropped.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .context import ContextTracker, context_dict
from .signals import SensorSample

log = logging.getLogger("farpoint.sources")

ROW_KEYS = ("t", "face", "distance_cm", "ear", "squint_ratio", "yaw", "pitch", "luma", "process", "title",
            "idle_s", "fullscreen", "theme", "brightness")


class ReplayClock:
    """Virtual clock for replay: epoch seconds = start wall time + trace time."""

    def __init__(self, base: float | None = None):
        self.base = time.time() if base is None else base
        self.t = self.base

    def set(self, trace_t: float) -> None:
        self.t = self.base + trace_t

    def __call__(self) -> float:
        return self.t


def load_trace(path: Path) -> tuple[dict, list[dict]]:
    header, rows = {}, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("kind") == "header":
            header = obj
        else:
            rows.append(obj)
    return header, rows


def sample_from_row(row: dict) -> SensorSample:
    return SensorSample(face=bool(row.get("face")), distance_cm=row.get("distance_cm"), ear=row.get("ear"),
                        squint_ratio=row.get("squint_ratio"), yaw_deg=row.get("yaw"), pitch_deg=row.get("pitch"),
                        luma=row.get("luma"))


class ReplaySource:
    def __init__(self, path: Path, tracker, on_time: Callable[[float], None], clock: ReplayClock,
                 speed: float = 1.0, loop: bool = False, env_sink=None, on_done=None, on_header=None):
        self.path = Path(path)
        self.tracker = tracker
        self.on_time = on_time
        self.clock = clock
        self.speed = max(0.01, float(speed))
        self.loop = loop
        self.env_sink = env_sink
        self.on_done = on_done
        self.on_header = on_header
        self.header, self.rows = load_trace(self.path)
        self.done = threading.Event()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self.camera_status = "off"
        self.rows_fed = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="farpoint-replay", daemon=True)
        self._thread.start()

    def pause(self, paused: bool) -> None:
        (self._paused.set if paused else self._paused.clear)()

    def calibrate(self, distance_cm: float):
        raise RuntimeError("calibration needs the live camera (replay mode)")

    def _apply_header(self) -> None:
        h = self.header
        if h.get("seed_bout_s"):
            self.tracker.seed_bout(float(h["seed_bout_s"]))
        if h.get("usual_distance_cm"):
            self.tracker.seed_usual_distance(float(h["usual_distance_cm"]))
        if self.on_header is not None:
            self.on_header(h)

    def feed(self, row: dict, last: dict) -> None:
        """Feed one row (also used by tests to step the replay by hand)."""
        self.clock.set(float(row["t"]))
        now = self.clock()
        proc = row.get("process", "")
        if proc != last.get("process"):
            if last.get("process") is not None:
                last["switch_t"] = now
            last["process"] = proc
        since = None if last.get("switch_t") is None else now - last["switch_t"]
        ctx = context_dict(proc, row.get("title", ""), bool(row.get("fullscreen")), float(row.get("idle_s", 30.0)),
                           since)
        ctx["title"] = row.get("title", "")
        if self.env_sink is not None:
            self.env_sink(ctx, theme=row.get("theme"), brightness=row.get("brightness"))
        self.tracker.update(now, sample_from_row(row), ctx)
        self.rows_fed += 1
        self.on_time(now)

    def _run(self) -> None:
        try:
            while True:
                self._apply_header()
                wall0 = time.monotonic()
                last: dict = {"process": None}
                for row in self.rows:
                    if self._stop.is_set():
                        return
                    while self._paused.is_set() and not self._stop.is_set():
                        time.sleep(0.1)
                        wall0 += 0.1
                    delay = wall0 + float(row["t"]) / self.speed - time.monotonic()
                    if delay > 0:
                        self._stop.wait(delay)
                    self.feed(row, last)
                if not self.loop or self._stop.is_set():
                    break
                self.clock.base = self.clock.t + 1.0
        except Exception:  # noqa: BLE001
            log.exception("replay failed")
        finally:
            self.done.set()
            if self.on_done is not None:
                self.on_done()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)


class TraceRecorder:
    """Writes live readings as a replay trace under <runtime>/recordings/ (numbers only)."""

    def __init__(self, runtime_dir: Path, header: dict | None = None):
        d = Path(runtime_dir) / "recordings"
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"trace-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self._f = self.path.open("w", encoding="utf-8")
        self._t0: float | None = None
        self._lock = threading.Lock()
        self._f.write(json.dumps({"kind": "header", "version": 1, **(header or {})}) + "\n")

    def write(self, t: float, sample: SensorSample, ctx: dict, theme: str | None, brightness: int | None) -> None:
        with self._lock:
            if self._f.closed:
                return
            if self._t0 is None:
                self._t0 = t
            row = {"t": round(t - self._t0, 3), "face": sample.face,
                   "distance_cm": None if sample.distance_cm is None else round(sample.distance_cm, 2),
                   "ear": None if sample.ear is None else round(sample.ear, 4),
                   "squint_ratio": None if sample.squint_ratio is None else round(sample.squint_ratio, 3),
                   "yaw": None if sample.yaw_deg is None else round(sample.yaw_deg, 1),
                   "pitch": None if sample.pitch_deg is None else round(sample.pitch_deg, 1),
                   "luma": None if sample.luma is None else round(sample.luma, 1),
                   "process": ctx.get("process", ""), "title": "", "idle_s": round(ctx.get("idle_s", 0.0), 1),
                   "fullscreen": bool(ctx.get("fullscreen")), "theme": theme, "brightness": brightness}
            self._f.write(json.dumps(row) + "\n")

    def close(self) -> None:
        with self._lock:
            self._f.close()


class LiveSource:
    """Webcam at ~10 fps -> MediaPipe numbers -> tracker. Frames stay in memory and are dropped."""

    FPS = 10.0
    CONTEXT_EVERY_S = 0.5

    def __init__(self, tracker, on_time: Callable[[float], None], clock=time.time, camera_index: int = 0,
                 calib=None, recorder: TraceRecorder | None = None, env_reader=None, keep_frame: bool = False,
                 on_status: Callable[[str], None] | None = None, on_toast=None):
        self.tracker = tracker
        self.on_time = on_time
        self.clock = clock
        self.camera_index = camera_index
        self.calib = calib
        self.recorder = recorder
        self.env_reader = env_reader
        self.keep_frame = keep_frame
        self.on_status = on_status
        self.on_toast = on_toast
        self.context = ContextTracker(clock)
        self.camera_status = "off"
        self._paused = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._calib_req: dict | None = None
        self._latest_frame = None  # vision mode only
        self.frames = 0
        self.faces = 0

    def _status(self, s: str) -> None:
        if s != self.camera_status:
            self.camera_status = s
            if self.on_status is not None:
                self.on_status(s)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="farpoint-camera", daemon=True)
        self._thread.start()

    def pause(self, paused: bool) -> None:
        (self._paused.set if paused else self._paused.clear)()

    def latest_frame_b64(self) -> str | None:
        """Vision mode only: the newest frame as base64 JPEG (quality 90, as in spike S2), built in
        memory on request for the LOCAL Decider. Never written to disk."""
        frame = self._latest_frame if self.keep_frame else None
        if frame is None or self.camera_status != "on":
            return None
        import base64

        import cv2
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None

    def calibrate(self, distance_cm: float, timeout_s: float = 30.0):
        """Ask the camera thread to collect a baseline at `distance_cm`. Blocks the caller."""
        req = {"distance_cm": float(distance_cm), "event": threading.Event(), "result": None, "error": None}
        self._calib_req = req
        req["event"].wait(timeout_s)
        if req["error"] or req["result"] is None:
            raise RuntimeError(req["error"] or "calibration timed out")
        return req["result"]

    def _run(self) -> None:
        from .sense import CALIBRATION_PATH, Calibration, FaceSensor, focal_length_px, frame_luma, open_camera
        if self.calib is None:
            try:
                self.calib = Calibration.load()
            except (OSError, ValueError):
                self.calib = Calibration(focal_px=600.0, ear_baseline=0.28)
                if self.on_toast:
                    self.on_toast("warning", "Not calibrated yet: distances are rough until you calibrate.")
        try:
            sensor = FaceSensor()
        except Exception as e:  # noqa: BLE001
            log.error("face model failed to load: %s", e)
            self._status("error")
            return
        cap = None
        ctx: dict = {}
        last_ctx = 0.0
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    self._latest_frame = None
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._status("paused")
                    self.tracker.update(self.clock(), None, None)
                    self.on_time(self.clock())
                    time.sleep(0.2)
                    continue
                if cap is None:
                    try:
                        cap = open_camera(self.camera_index)
                        self._status("on")
                    except RuntimeError as e:
                        log.error("%s", e)
                        self._status("error")
                        self._stop.wait(5)
                        continue
                t_frame = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    self._stop.wait(0.1)
                    continue
                t = self.clock()
                if self._calib_req is not None:
                    self._do_calibration(sensor, cap, focal_length_px, Calibration, CALIBRATION_PATH)
                    continue
                reading = sensor.read(frame, self.calib)
                luma = frame_luma(frame)
                # Vision mode keeps only the newest frame, in memory; otherwise it is dropped here.
                self._latest_frame = frame if self.keep_frame else None
                del frame
                self.frames += 1
                if t - last_ctx >= self.CONTEXT_EVERY_S:
                    ctx = self.context.poll()
                    last_ctx = t
                sample = SensorSample(face=reading is not None,
                                      distance_cm=reading.distance_cm if reading else None,
                                      ear=reading.ear if reading else None,
                                      squint_ratio=reading.squint_ratio if reading else None,
                                      yaw_deg=reading.yaw_deg if reading else None,
                                      pitch_deg=reading.pitch_deg if reading else None, luma=luma)
                if reading is not None:
                    self.faces += 1
                self.tracker.update(t, sample, ctx)
                if self.recorder is not None:
                    env = self.env_reader() if self.env_reader else {}
                    self.recorder.write(t, sample, ctx, env.get("theme"), env.get("brightness_pct"))
                self.on_time(t)
                spare = 1.0 / self.FPS - (time.monotonic() - t_frame)
                if spare > 0:
                    self._stop.wait(spare)
        finally:
            if cap is not None:
                cap.release()
            sensor.close()
            self._status("off")

    def _do_calibration(self, sensor, cap, focal_length_px, Calibration, path) -> None:
        req, self._calib_req = self._calib_req, None
        iris, ear = [], []
        deadline = time.time() + 20
        while len(iris) < 60 and time.time() < deadline:
            ok, frame = cap.read()
            if not ok:
                continue
            r = sensor.read(frame)
            del frame
            if r:
                iris.append(r.iris_px)
                ear.append(r.ear)
        if not iris:
            req["error"] = "no face detected during calibration"
        else:
            calib = Calibration(focal_px=focal_length_px(statistics.median(iris), req["distance_cm"]),
                                ear_baseline=statistics.median(ear))
            calib.save(path)
            self.calib = calib
            req["result"] = calib
        req["event"].set()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
