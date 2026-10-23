"""Helpers to switch the local Decider between text and vision mode (via start_decider.ps1).

Used by scripts/smoke_vision.py and scripts/human_session.py. Everything stays on
127.0.0.1; caches stay under FARPOINT_RUNTIME (start_decider.ps1 sets them).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farpoint.decide import client  # noqa: E402
from farpoint.vision import S2_QUESTIONS, S2_STATE  # noqa: E402

START_SCRIPT = ROOT / "scripts" / "start_decider.ps1"
RUNTIME = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))


def health() -> dict | None:
    return client().health_info(timeout=3.0, retries=0)


def start(vision: bool) -> subprocess.Popen:
    """Restart the server in the background (start_decider.ps1 stops the running one first).

    Output goes to a log file, not a pipe: the server is a grandchild that inherits the handle,
    so a pipe would never reach EOF."""
    args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(START_SCRIPT)]
    if vision:
        args.append("-Vision")
    log_path = RUNTIME / "logs" / f"start-decider-{'vision' if vision else 'text'}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        return subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def wait(proc: subprocess.Popen, vision: bool, timeout_s: float = 480.0) -> dict:
    """Wait until the server reports the wanted mode (or the start script fails / times out)."""
    t0 = time.time()
    info = None
    while time.time() - t0 < timeout_s:
        info = health()
        if info and bool(info.get("vision")) == vision and proc.poll() is not None:
            break
        if proc.poll() not in (None, 0):
            break  # start_decider.ps1 failed
        time.sleep(2)
    ok = bool(info and bool(info.get("vision")) == vision)
    return {"ok": ok, "vision": vision, "seconds": round(time.time() - t0, 1), "rc": proc.poll()}


def restart(vision: bool, timeout_s: float = 480.0) -> dict:
    info = health()
    if info and bool(info.get("vision")) == vision:
        return {"ok": True, "vision": vision, "seconds": 0.0, "note": "already in this mode"}
    return wait(start(vision), vision, timeout_s)


def synthetic_frame_b64() -> str:
    """A plain gray 640x480 JPEG, made in memory: warms the vision kernels without the camera."""
    import base64

    import cv2
    import numpy as np
    img = np.full((480, 640, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode("ascii")


def warm_up_vision(timeout_s: float = 400.0) -> dict:
    """One image request. The first one after a fresh Triton cache can take ~2-3 min."""
    t0 = time.perf_counter()
    try:
        client().ask(S2_STATE, S2_QUESTIONS, images=[synthetic_frame_b64()], timeout=timeout_s)
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        ok, err = False, f"{type(e).__name__}: {e}"
    return {"ok": ok, "seconds": round(time.perf_counter() - t0, 1), "error": err}


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                      text=True)
        return int(out.strip().splitlines()[0])
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
