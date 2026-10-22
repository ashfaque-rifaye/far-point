"""Settings from the command line and environment."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

from patterns.reflex_gate import Thresholds

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = "0.2.0"
DEFAULT_RUNTIME = r"E:\farpoint-runtime"
DEFAULT_TRACE = ROOT / "farpoint" / "replay" / "demo_session.jsonl"
ALLOWED_HOST = "127.0.0.1"


@dataclass
class Settings:
    mode: str = "live"  # live | replay
    trace: Path | None = None
    events: Path | None = None
    fake_decider: bool = False
    no_bedrock: bool = False
    dry_run: bool = False
    actuate: bool = False  # replay only: drive the real actuators
    # None = automatic: on only if results/s2_decision.json records an S2 pass AND the Decider
    # server runs with --vision (farpoint/vision.py). True/False force it.
    vision: bool | None = field(default_factory=lambda: {"1": True, "0": False}.get(os.environ.get("FARPOINT_VISION", "")))
    record: bool = False
    host: str = ALLOWED_HOST
    port: int = 8765
    decider_url: str = field(default_factory=lambda: os.environ.get(
        "FARPOINT_DECIDER_URL", "http://127.0.0.1:8099/v1/systemone"))
    runtime_dir: Path = field(default_factory=lambda: Path(os.environ.get("FARPOINT_RUNTIME", DEFAULT_RUNTIME)))
    web_dist: Path = field(default_factory=lambda: Path(os.environ.get("FARPOINT_WEB_DIST", ROOT / "web" / "dist")))
    period_s: float = 2.5
    speed: float = 1.0
    loop_replay: bool = False
    camera_index: int = 0
    profile_name: str = field(default_factory=lambda: os.environ.get("FARPOINT_PROFILE_NAME", "you"))
    thresholds: Thresholds = field(default_factory=Thresholds)
    coach_model: str = field(default_factory=lambda: os.environ.get("FARPOINT_COACH_MODEL", "us.amazon.nova-lite-v1:0"))
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))
    decider_timeout_s: float = 4.0

    @property
    def actuators_dry(self) -> bool:
        return self.dry_run or (self.mode == "replay" and not self.actuate)

    @property
    def profile_dir(self) -> Path:
        # Replay never touches the live profile (doctrine, stats, preferences, moments).
        return self.runtime_dir / ("replay" if self.mode == "replay" else "") / "profile"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m farpoint.app", description="Far Point backend (localhost only)")
    ap.add_argument("--mode", choices=["live", "replay"], default="live")
    ap.add_argument("--trace", type=Path, help="replay trace (JSONL of numeric readings)")
    ap.add_argument("--events", type=Path, help="re-emit a recorded bus event trace to the UI; runs no loop")
    ap.add_argument("--fake-decider", action="store_true", help="offline oracle instead of the local Decider")
    ap.add_argument("--no-bedrock", action="store_true", help="disable the Nova coach and escalation")
    ap.add_argument("--dry-run", action="store_true", help="never change zoom, brightness or theme")
    ap.add_argument("--actuate", action="store_true", help="replay: drive the real actuators")
    vis = ap.add_mutually_exclusive_group()
    vis.add_argument("--vision", action="store_true", dest="vision_on",
                     help="force vision on: one webcam frame per tick to the LOCAL Decider")
    vis.add_argument("--no-vision", action="store_true", dest="vision_off", help="force text-only")
    ap.add_argument("--record", action="store_true", help="live: record numeric readings and bus events")
    ap.add_argument("--host", default=ALLOWED_HOST, help="must be 127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed")
    ap.add_argument("--loop-replay", action="store_true", help="restart the replay trace when it ends")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--period", type=float, default=2.5, help="seconds between decisions")
    return ap


def parse_args(argv: list[str] | None = None) -> Settings:
    a = build_parser().parse_args(argv)
    s = Settings(mode=a.mode, trace=a.trace, events=a.events, fake_decider=a.fake_decider, no_bedrock=a.no_bedrock,
                 dry_run=a.dry_run, actuate=a.actuate, record=a.record, host=a.host, port=a.port, speed=a.speed,
                 loop_replay=a.loop_replay, camera_index=a.camera, period_s=a.period)
    if a.vision_on:
        s.vision = True
    elif a.vision_off:
        s.vision = False
    if s.mode == "replay" and s.trace is None and s.events is None:
        s.trace = DEFAULT_TRACE
    return s
