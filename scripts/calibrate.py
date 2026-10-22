"""One-time calibration: sit at a measured distance, eyes relaxed and open.

Usage:
  python scripts/calibrate.py --distance-cm 50          # calibrate, then show live distance
  python scripts/calibrate.py --live --seconds 10       # live readout with existing calibration
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farpoint.sense import CALIBRATION_PATH, Calibration, FaceSensor, focal_length_px, open_camera  # noqa: E402


def collect(sensor, cap, n):
    iris, ear = [], []
    deadline = time.time() + 20
    while len(iris) < n and time.time() < deadline:
        ok, frame = cap.read()
        if not ok:
            continue
        r = sensor.read(frame)
        if r:
            iris.append(r.iris_px)
            ear.append(r.ear)
    if not iris:
        raise SystemExit("No face detected. Check lighting and camera.")
    return statistics.median(iris), statistics.median(ear)


def live(sensor, cap, calib, seconds):
    end = time.time() + seconds
    while time.time() < end:
        ok, frame = cap.read()
        if not ok:
            continue
        r = sensor.read(frame, calib)
        if r:
            print(f"distance={r.distance_cm:5.1f} cm  ear={r.ear:.3f}  squint_ratio={r.squint_ratio:.2f}", flush=True)
        time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distance-cm", type=float, help="Measured eye-to-camera distance")
    ap.add_argument("--live", action="store_true", help="Skip calibration, use saved file")
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--frames", type=int, default=60)
    a = ap.parse_args()

    sensor, cap = FaceSensor(), open_camera(a.camera)
    try:
        if a.live:
            calib = Calibration.load()
        else:
            if not a.distance_cm:
                ap.error("--distance-cm is required unless --live")
            print(f"Hold still at {a.distance_cm} cm, eyes relaxed...")
            iris, ear = collect(sensor, cap, a.frames)
            calib = Calibration(focal_px=focal_length_px(iris, a.distance_cm), ear_baseline=ear)
            calib.save()
            print(f"Saved {CALIBRATION_PATH}: focal_px={calib.focal_px:.1f} ear_baseline={calib.ear_baseline:.3f}")
        live(sensor, cap, calib, a.seconds)
    finally:
        cap.release()
        sensor.close()


if __name__ == "__main__":
    main()
