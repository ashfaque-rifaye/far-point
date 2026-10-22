"""Wires Far Point together for live mode, replay mode and event replay.

Threads: the signal source (camera or replay) feeds the tracker and calls `on_time`;
the reflex loop runs on its own thread in live mode (inline on the replay clock in replay
mode); the coach and escalator have 1-worker executors; uvicorn owns the asyncio loop.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from patterns.reflex_gate import DeciderHttpClient, FakeDecider, InterruptGate, ScriptedModel, oracle

from . import contract
from .act import Actuators
from .agent import INTERRUPTIVE, make_reflex_agent
from .breaks import BreakManager
from .bus import EventBus, EventRecorder
from .coach import Coach
from .config import APP_VERSION, Settings
from .confirm import ConfirmBroker
from .doctrine import DoctrineStore
from .escalate import NovaEscalator
from .loop import ReflexLoop
from .memory import MomentLog, PreferenceStore
from .predicates import PREDICATES
from .signals import SignalTracker
from .sources import LiveSource, ReplayClock, ReplaySource, TraceRecorder
from .stats import StatsStore
from .tools import ToolContext
from .verify import Verifier

log = logging.getLogger("farpoint.runtime")

FAKE_MODEL_NAME = "FAKE oracle (tests/demo)"
SIGNALS_EVERY_S = 0.2  # 5 Hz
STATS_EVERY_S = 10.0
HEALTH_EVERY_S = 10.0


def bedrock_credentials() -> bool:
    try:
        import boto3
        return boto3.Session().get_credentials() is not None
    except Exception:  # noqa: BLE001
        return False


class EventsReplay:
    """Re-emits a recorded bus trace (JSONL envelopes) with its original timing. No loop runs."""

    def __init__(self, path: Path, bus: EventBus, speed: float = 1.0, on_done=None):
        self.path, self.bus, self.speed, self.on_done = Path(path), bus, max(0.01, speed), on_done
        self.done = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.camera_status = "off"
        self.count = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="farpoint-events", daemon=True)
        self._thread.start()

    def pause(self, paused: bool) -> None:  # nothing to pause meaningfully
        pass

    def calibrate(self, distance_cm: float):
        raise RuntimeError("calibration needs the live camera (event replay)")

    def _run(self) -> None:
        prev = None
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if self._stop.is_set():
                    return
                if not line.strip():
                    continue
                env = json.loads(line)
                if prev is not None:
                    self._stop.wait(max(0.0, (env["t"] - prev) / 1000.0 / self.speed))
                prev = env["t"]
                self.bus.publish(env["type"], env["data"], force=True)
                self.count += 1
        finally:
            self.done.set()
            if self.on_done:
                self.on_done()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)


class Runtime:
    def __init__(self, settings: Settings, decider=None, escalator=None, coach_model_factory=None, startfile=None,
                 bedrock_available: bool | None = None, deny_without_client: bool = True):
        s = self.settings = settings
        self.replay = s.mode == "replay" or s.events is not None
        self.clock = ReplayClock() if s.mode == "replay" and s.events is None else time.time
        profile = s.profile_dir
        self.recorder = EventRecorder(s.runtime_dir / "recordings" / f"events-{time.strftime('%Y%m%d-%H%M%S')}.jsonl") \
            if s.record else None
        self.bus = EventBus(recorder=self.recorder)
        self.broker = ConfirmBroker(self.bus, deny_without_client=deny_without_client)
        self.store = DoctrineStore(profile)
        self.stats = StatsStore(profile, self.clock)
        self.prefs = PreferenceStore(profile / "preferences.json")
        self.moments = MomentLog(profile / "moments.jsonl", self.clock)
        self.tracker = SignalTracker(self.store.active.limits, self.clock)
        self.actuators = Actuators.dry() if s.actuators_dry else Actuators.real(s.runtime_dir)
        self.verifier = Verifier(self.bus, self.tracker, self.stats, self.prefs, self.clock)
        self.breaks = BreakManager(self.bus, self.actuators.overlay, self.tracker, self.stats, self.clock,
                                   on_outcome=self.verifier.on_break_outcome)
        self.tool_ctx = ToolContext(self.actuators, self.breaks, self.broker, self.bus, self.tracker, self.prefs,
                                    self.moments)

        # Decider: the real local server, or a clearly labelled fake oracle.
        if decider is not None:
            self.decider = decider
        elif s.fake_decider:
            self.decider = FakeDecider(oracle(self._oracle_rule, self._oracle_interrupt))
        else:
            self.decider = DeciderHttpClient(s.decider_url)
        self.decider_model = FAKE_MODEL_NAME if isinstance(self.decider, FakeDecider) else "strands-decider-2B"
        self.decider_device = "cpu" if isinstance(self.decider, FakeDecider) else "cuda"
        self.decider_status = "loading"

        has_creds = bedrock_credentials() if bedrock_available is None else bedrock_available
        self.bedrock_status = "off" if (s.no_bedrock or not has_creds) else "ready"
        bedrock_on = self.bedrock_status != "off"

        self.gate = InterruptGate(self.decider, lambda: self.loop.current_state_text, INTERRUPTIVE, s.thresholds)
        # The loop never invokes this model; with Bedrock off it would raise if anything tried.
        reflex_model = None if bedrock_on else ScriptedModel(fail_if_called=True)
        self.agent = make_reflex_agent(self.tool_ctx, model=reflex_model, interrupt_gate=self.gate)
        if escalator is not None:
            self.escalator = escalator
        elif bedrock_on:
            self.escalator = NovaEscalator(model_id=s.coach_model, region=s.region, stats=self.stats,
                                           moments=self.moments, clock=self.clock)
        else:
            self.escalator = None
        self.coach = Coach(self.bus, self.store, self.stats, self.moments, self.broker,
                           model_factory=coach_model_factory, enabled=bedrock_on or coach_model_factory is not None,
                           startfile=startfile, clock=self.clock, model_id=s.coach_model)
        self.loop = ReflexLoop(tracker=self.tracker, doctrine_store=self.store, decider=self.decider, agent=self.agent,
                               interrupt_gate=self.gate, verifier=self.verifier, prefs=self.prefs,
                               moments=self.moments, stats=self.stats, bus=self.bus, actuators=self.actuators,
                               breaks=self.breaks, tool_ctx=self.tool_ctx, thresholds=s.thresholds,
                               escalator=self.escalator, clock=self.clock, period_s=s.period_s,
                               decider_timeout_s=s.decider_timeout_s, vision=s.vision,
                               image_provider=self._images if s.vision else None)

        self.trace_recorder = None
        if s.events is not None:
            self.source = EventsReplay(s.events, self.bus, speed=s.speed, on_done=self._replay_done)
        elif s.mode == "replay":
            self.source = ReplaySource(s.trace, self.tracker, self.on_time, self.clock, speed=s.speed,
                                       loop=s.loop_replay, env_sink=self.actuators.observe_env,
                                       on_done=self._replay_done)
        else:
            if s.record:
                self.trace_recorder = TraceRecorder(s.runtime_dir, {"profile": s.profile_name})
            self.source = LiveSource(self.tracker, self.on_time, self.clock, camera_index=s.camera_index,
                                     recorder=self.trace_recorder, env_reader=self.actuators.state,
                                     keep_frame=s.vision, on_status=lambda st: self.send_hello(),
                                     on_toast=self.bus.toast)
        self._last_sig = 0.0
        self._last_stats = 0.0
        self._stop = threading.Event()
        self._health_thread: threading.Thread | None = None
        self._last_hello: dict | None = None
        self.started = False
        self.stopped = False
        self.restored: dict | None = None

    # ---- fake oracle (tests/demo only) -----------------------------------------------------
    def _oracle_rule(self, name: str) -> bool | None:
        f = self.loop.current_facts
        d = self.store.active
        try:
            rule = d.rule(int(name.split("_", 1)[1]))
        except (ValueError, IndexError):
            return None
        pred = PREDICATES.get(rule.tool) if rule else None
        return bool(pred(f, d.limits)) if pred else None

    def _oracle_interrupt(self) -> bool:
        hint = self.loop.current_facts.interrupt_ok_hint
        return True if hint is None else bool(hint)

    def _images(self) -> list[str]:
        from .context import capture_thumbnail
        frame = self.source.latest_frame_b64() if hasattr(self.source, "latest_frame_b64") else None
        return [frame, capture_thumbnail()] if frame else []

    # ---- hello / status ---------------------------------------------------------------------
    def camera_status(self) -> str:
        if self.replay:
            return "paused" if self.loop.paused else "off"
        return getattr(self.source, "camera_status", "off")

    def hello(self) -> dict:
        s = self.settings
        return {
            "mode": "replay" if self.replay else "live",
            "app_version": APP_VERSION,
            "profile_name": s.profile_name,
            "decider": {"status": self.decider_status, "model": self.decider_model, "device": self.decider_device,
                        "vision": bool(s.vision)},
            "bedrock": {"status": self.bedrock_status,
                        "model": s.coach_model if self.bedrock_status != "off" else None},
            "camera": {"status": self.camera_status()},
        }

    def send_hello(self, force: bool = False) -> None:
        h = self.hello()
        if force or h != self._last_hello:
            self._last_hello = h
            self.bus.publish("hello", h)

    def _poll_health(self) -> None:
        info = self.decider.health_info() if hasattr(self.decider, "health_info") else None
        if info is None:
            self.decider_status = "down"
        else:
            self.decider_status = "ready"
            if not isinstance(self.decider, FakeDecider):
                self.decider_model = str(info.get("model") or self.decider_model)
                self.decider_device = str(info.get("device") or self.decider_device)
        self.send_hello()

    def _health_loop(self) -> None:
        while not self._stop.wait(HEALTH_EVERY_S):
            try:
                self._poll_health()
            except Exception:  # noqa: BLE001
                log.exception("health poll failed")

    # ---- the pulse: called by the source after every sample ------------------------------------
    def on_time(self, t: float) -> None:
        self.breaks.on_time(t)
        self.verifier.on_time(t)
        if self.settings.mode == "replay":
            self.loop.on_time(t)
        if t - self._last_sig >= SIGNALS_EVERY_S:
            self._last_sig = t
            self.bus.publish("signals", self.tracker.signals_payload(zoom_step=self.actuators.zoom.zoom_step()))
        if t - self._last_stats >= STATS_EVERY_S:
            self._last_stats = t
            self.publish_stats()
        self.stats.on_time(t)
        self.coach.on_time(t)

    def publish_stats(self) -> None:
        self.stats.update_from_tracker(self.tracker.stats_view())
        self.bus.publish("stats", self.stats.snapshot())

    def _replay_done(self) -> None:
        self.publish_stats()
        self.bus.toast("info", "Replay finished. Recorded numbers only; nothing on your screen was changed."
                       if self.actuators.dry_run else "Replay finished.")
        self.send_hello()

    # ---- lifecycle ------------------------------------------------------------------------------
    def start(self) -> None:
        if self.started:
            return
        self.started = True
        if not self.actuators.dry_run:
            rec = self.actuators.recover()
            if rec:
                self.bus.toast("info", "Restored settings left over from a previous run.")
        self.bus.publish("doctrine", self.store.current_draft.to_contract())
        for p in self.coach.proposals.values():
            if p["data"]["status"] == "pending":
                self.bus.publish("proposal", p["data"])
        self.publish_stats()
        self._poll_health()
        self._health_thread = threading.Thread(target=self._health_loop, name="farpoint-health", daemon=True)
        self._health_thread.start()
        self.source.start()
        if self.settings.mode == "live" and self.settings.events is None:
            self.loop.start()
        log.info("Far Point %s started: mode=%s decider=%s bedrock=%s actuators=%s", APP_VERSION,
                 "replay" if self.replay else "live", self.decider_model, self.bedrock_status,
                 "dry-run" if self.actuators.dry_run else "real")

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self._stop.set()
        for part in (self.source, self.loop):
            try:
                part.stop()
            except Exception:  # noqa: BLE001
                log.exception("stop failed")
        try:
            self.broker.deny_all()
            self.restored = self.actuators.restore_all()
            log.info("restored on exit: %s (%s actuators)", self.restored,
                     "dry-run" if self.actuators.dry_run else "real")
        finally:
            try:
                self.actuators.overlay.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self.stats.save()
            self.coach.close()
            if self.escalator is not None and hasattr(self.escalator, "close"):
                self.escalator.close()
            for r in (self.recorder, self.trace_recorder):
                if r is not None:
                    r.close()

    # ---- commands from the UI ---------------------------------------------------------------
    def handle_raw(self, raw: str) -> None:
        cmd = None
        try:
            cmd = json.loads(raw)
            contract.validate_command(cmd)
        except Exception:  # noqa: BLE001 - unknown/invalid -> warning toast, per contract
            name = cmd.get("name") if isinstance(cmd, dict) else None
            self.bus.toast("warning", f"Unknown or invalid command{f' {name!r}' if name else ''}; ignored.")
            return
        self.handle_command(cmd["name"], cmd.get("args") or {})

    def handle_command(self, name: str, args: dict) -> None:
        c = self.coach
        if name == "set_eye_description":
            c.submit(c.compile_doctrine, args["text"])
        elif name == "approve_doctrine":
            c.submit(c.adopt, int(args["version"]))
        elif name == "approve_proposal":
            c.submit(c.approve_proposal, args["id"])
        elif name == "reject_proposal":
            c.submit(c.reject_proposal, args["id"])
        elif name == "request_report":
            c.submit(c.report, args["period"])
        elif name == "draft_exam_email":
            c.submit(c.draft_exam)
        elif name == "confirm":
            if not self.broker.resolve(args["request_id"], bool(args["approve"])):
                self.bus.toast("warning", "That confirmation request is no longer open.")
        elif name == "pause_camera":
            paused = bool(args["paused"])
            self.source.pause(paused)
            self.loop.paused = paused
            if not self.replay:
                deadline = time.time() + 2
                want = "paused" if paused else "on"
                while getattr(self.source, "camera_status", want) != want and time.time() < deadline:
                    time.sleep(0.05)
            self.send_hello(force=True)
        elif name == "skip_break":
            if not self.breaks.skip(args["id"]):
                self.bus.toast("warning", "No running break with that id.")
        elif name == "start_calibration":
            if self.replay:
                self.bus.toast("warning", "Calibration needs the live camera; this is replay mode.")
                return
            try:
                calib = self.source.calibrate(float(args["distance_cm"]))
                self.bus.toast("success", f"Calibration saved: baseline {float(args['distance_cm']):.0f} cm "
                                          f"(eye opening {calib.ear_baseline:.3f}).")
            except Exception as e:  # noqa: BLE001
                self.bus.toast("warning", f"Calibration failed: {e}")
