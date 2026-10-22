"""On-device sensing: viewing distance and squint from MediaPipe FaceLandmarker.

Runs on CPU. No frames leave the machine.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

IRIS_DIAMETER_MM = 11.7

# FaceLandmarker (478 points) indices. Iris: 468-472 and 473-477.
RIGHT_IRIS_H = (469, 471)
LEFT_IRIS_H = (474, 476)
# Eye contour points for EAR: p1, p2, p3, p4, p5, p6
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
LEFT_EYE = (362, 385, 387, 263, 373, 380)

RUNTIME_DIR = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))
MODEL_PATH = Path(os.environ.get("FARPOINT_FACE_MODEL", RUNTIME_DIR / "models" / "face_landmarker.task"))
CALIBRATION_PATH = Path(os.environ.get("FARPOINT_CALIBRATION", RUNTIME_DIR / "calibration.local.json"))


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def iris_diameter_px(pts) -> float:
    """Mean horizontal iris diameter of both eyes, in pixels."""
    r = _dist(pts[RIGHT_IRIS_H[0]], pts[RIGHT_IRIS_H[1]])
    l = _dist(pts[LEFT_IRIS_H[0]], pts[LEFT_IRIS_H[1]])
    return (r + l) / 2.0


def eye_aspect_ratio(pts) -> float:
    """Mean EAR of both eyes. Lower means more closed / squinting."""
    def ear(idx):
        p1, p2, p3, p4, p5, p6 = (pts[i] for i in idx)
        return (_dist(p2, p6) + _dist(p3, p5)) / (2.0 * _dist(p1, p4))
    return (ear(RIGHT_EYE) + ear(LEFT_EYE)) / 2.0


def focal_length_px(iris_px: float, distance_cm: float) -> float:
    return iris_px * (distance_cm * 10.0) / IRIS_DIAMETER_MM


def distance_cm(iris_px: float, focal_px: float) -> float:
    return focal_px * IRIS_DIAMETER_MM / iris_px / 10.0


@dataclass
class Calibration:
    focal_px: float
    ear_baseline: float

    def save(self, path: Path = CALIBRATION_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, path: Path = CALIBRATION_PATH) -> "Calibration":
        return cls(**json.loads(path.read_text()))


@dataclass
class Reading:
    iris_px: float
    ear: float
    distance_cm: float | None = None
    squint_ratio: float | None = None  # ear / baseline; < ~0.75 suggests squinting


class FaceSensor:
    """Thin wrapper over MediaPipe FaceLandmarker in VIDEO mode."""

    def __init__(self, model_path: Path = MODEL_PATH):
        from mediapipe.tasks.python import BaseOptions, vision
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
        )
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self._ts = 0

    def read(self, frame_bgr, calib: Calibration | None = None) -> Reading | None:
        import cv2
        import mediapipe as mp
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self._ts += 33
        res = self._lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), self._ts)
        if not res.face_landmarks:
            return None
        pts = [(p.x * w, p.y * h) for p in res.face_landmarks[0]]
        r = Reading(iris_px=iris_diameter_px(pts), ear=eye_aspect_ratio(pts))
        if calib:
            r.distance_cm = distance_cm(r.iris_px, calib.focal_px)
            r.squint_ratio = r.ear / calib.ear_baseline
        return r

    def close(self) -> None:
        self._lm.close()


def open_camera(index: int = 0):
    import cv2
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam {index}")
    return cap
