"""Spike S2: Decider image mode over webcam frames.

Frames never enter the repository. Live frames stay in memory; a guided labeled
capture writes to FARPOINT_RUNTIME (E:\\farpoint-runtime by default), outside the repo.

Usage:
  python eval/spike_s2.py latency --n 40          # VRAM peak + latency on live frames (no labels)
  python eval/spike_s2.py capture                  # guided labeled capture (a person poses on prompts)
  python eval/spike_s2.py score                    # accuracy on the captured labeled frames
Writes results/s2_<mode>.json.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farpoint.decide import ask  # noqa: E402

RUNTIME = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))
FRAMES_DIR = RUNTIME / "s2-frames"
WARMUP = 3
P50_LIMIT_S = 1.5
VRAM_LIMIT_MIB = int(7.4 * 1024)
ACC_LIMIT = 0.85

STATE = "Webcam frame of the user at their laptop. The camera sits at the top edge of the screen."
QUESTIONS = {
    "glasses_on": {
        "type": "noul",
        "instructions": "Is the person in the image wearing glasses on their face?",
        "criteria": {
            "true": "eyeglass frames or lenses are visible on the person's face, in front of the eyes",
            "false": "no glasses on the face; glasses held in a hand or absent count as false",
        },
    },
    "rubbing_eyes": {
        "type": "noul",
        "instructions": "Is the person rubbing or touching their eyes?",
        "criteria": {
            "true": "a hand or fingers touch or cover one or both eyes",
            "false": "hands are away from the eyes",
        },
    },
    "looking_far_away": {
        "type": "noul",
        "instructions": "Is the person looking far away from the screen?",
        "criteria": {
            "true": "head and gaze are turned away from the screen toward a distant point, such as across the room or out of a window",
            "false": "the person is looking at the screen or the camera",
        },
    },
}
GATED = ("glasses_on", "looking_far_away")

# Guided capture plan: (prompt, labels). 8 frames per pose, 6 poses = 48 frames.
POSES = [
    ("Glasses ON, look at the screen", {"glasses_on": True, "looking_far_away": False, "rubbing_eyes": False}),
    ("Glasses ON, look far away (across the room / out of a window)", {"glasses_on": True, "looking_far_away": True, "rubbing_eyes": False}),
    ("Glasses OFF, look at the screen", {"glasses_on": False, "looking_far_away": False, "rubbing_eyes": False}),
    ("Glasses OFF, look far away (across the room / out of a window)", {"glasses_on": False, "looking_far_away": True, "rubbing_eyes": False}),
    ("Glasses OFF, rub your eyes", {"glasses_on": False, "looking_far_away": False, "rubbing_eyes": True}),
    ("Glasses ON, look at the screen, lean in close", {"glasses_on": True, "looking_far_away": False, "rubbing_eyes": False}),
]
FRAMES_PER_POSE = 8


class VramMonitor(threading.Thread):
    def __init__(self, period=0.2):
        super().__init__(daemon=True)
        self.period, self.samples, self._halt = period, [], threading.Event()

    def run(self):
        while not self._halt.is_set():
            self.samples.append(gpu_used_mib())
            time.sleep(self.period)

    def stop(self):
        self._halt.set()
        self.join()
        return max(self.samples) if self.samples else None


def gpu_used_mib() -> int:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True
    )
    return int(out.strip().splitlines()[0])


def encode(frame) -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def ask_frame(b64: str) -> tuple[dict, float]:
    body = {"state": STATE, "questions": QUESTIONS}
    t0 = time.perf_counter()
    resp = ask_images(body, [b64])
    return resp, time.perf_counter() - t0


def ask_images(body: dict, images: list[str], timeout: float = 600.0) -> dict:
    # farpoint.decide.ask has no images argument yet; reuse its lock and URL here.
    import urllib.request
    from farpoint import decide
    data = json.dumps({**body, "images": images}).encode()
    req = urllib.request.Request(decide.DECIDER_URL, data=data, headers={"Content-Type": "application/json"})
    with decide._lock:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())


def pct(xs, q):
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def cmd_latency(a):
    from farpoint.sense import open_camera
    cap = open_camera(a.camera)
    try:
        for _ in range(10):
            cap.read()
        frames = []
        while len(frames) < a.n + WARMUP:
            ok, f = cap.read()
            if ok:
                frames.append(encode(f))
            time.sleep(0.05)
    finally:
        cap.release()
    mon = VramMonitor()
    mon.start()
    lat, answers = [], []
    try:
        for i, b in enumerate(frames):
            resp, dt = ask_frame(b)
            if i >= WARMUP:
                lat.append(dt)
                answers.append({k: v["noul"] for k, v in resp["answers"].items()})
    finally:
        peak = mon.stop()
    summary = {
        "n": len(lat),
        "client_s": {"p50": statistics.median(lat), "p90": pct(lat, 0.9), "max": max(lat)},
        "peak_gpu_used_mib": peak,
        "vram_limit_mib": VRAM_LIMIT_MIB,
        "baseline_no_decider_mib": a.baseline_mib,
        "vision_server_footprint_mib": (peak - a.baseline_mib) if a.baseline_mib else None,
        "pass_latency": statistics.median(lat) <= P50_LIMIT_S,
        "pass_vram": peak is not None and peak <= VRAM_LIMIT_MIB,
        "unlabeled_answer_means": {k: statistics.mean(x[k] for x in answers) for k in QUESTIONS},
        "note": "live frames held in memory only; none written to disk",
    }
    out = ROOT / "results" / "s2_latency.json"
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def cmd_capture(a):
    import cv2
    from farpoint.sense import open_camera
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    cap = open_camera(a.camera)
    labels = []
    try:
        for pi, (prompt, lab) in enumerate(POSES):
            print(f"\n[{pi + 1}/{len(POSES)}] {prompt}. Capturing in 5 s...", flush=True)
            end = time.time() + 5
            while time.time() < end:
                cap.read()
            for k in range(FRAMES_PER_POSE):
                ok, f = cap.read()
                if not ok:
                    continue
                name = f"pose{pi}_{k}.jpg"
                cv2.imwrite(str(FRAMES_DIR / name), f)
                labels.append({"file": name, **lab})
                t = time.time() + 0.4
                while time.time() < t:
                    cap.read()
            print("  done", flush=True)
    finally:
        cap.release()
    (FRAMES_DIR / "labels.json").write_text(json.dumps(labels, indent=2))
    print(f"wrote {len(labels)} labeled frames to {FRAMES_DIR}")


def cmd_score(a):
    labels = json.loads((FRAMES_DIR / "labels.json").read_text())
    for lab in labels[:WARMUP]:
        ask_frame(base64.b64encode((FRAMES_DIR / lab["file"]).read_bytes()).decode("ascii"))
    rows, lat = [], []
    for lab in labels:
        b = base64.b64encode((FRAMES_DIR / lab["file"]).read_bytes()).decode("ascii")
        resp, dt = ask_frame(b)
        lat.append(dt)
        rows.append({"file": lab["file"], "label": {k: lab[k] for k in QUESTIONS},
                     "p": {k: v["noul"] for k, v in resp["answers"].items()}})
    acc = {k: sum((r["p"][k] > 0.5) == r["label"][k] for r in rows) / len(rows) for k in QUESTIONS}
    summary = {
        "n": len(rows),
        "accuracy": acc,
        "client_s": {"p50": statistics.median(lat), "p90": pct(lat, 0.9)},
        "pass_accuracy": all(acc[k] >= ACC_LIMIT for k in GATED),
    }
    (ROOT / "results" / "s2_score.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["latency", "capture", "score"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--baseline-mib", type=int, default=0, help="GPU memory used with no Decider loaded")
    a = ap.parse_args()
    {"latency": cmd_latency, "capture": cmd_capture, "score": cmd_score}[a.mode](a)


if __name__ == "__main__":
    main()
