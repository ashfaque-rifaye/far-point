"""Camera preview window for the guided setup (calibration, labeled capture). Local only.

Shows the live webcam image mirrored, with the current prompt and a countdown drawn on top.
The overlay is drawn on a display copy; nothing shown here is saved. Keys work in the
preview window and in the console window.
"""
from __future__ import annotations

import numpy as np

FONT = 0  # cv2.FONT_HERSHEY_SIMPLEX


def console_key() -> str | None:
    try:
        import msvcrt
    except ImportError:
        return None
    if not msvcrt.kbhit():
        return None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):  # arrow / function keys arrive as two codes
        msvcrt.getwch()
        return None
    return "enter" if ch in ("\r", "\n") else ch.lower()


class Preview:
    def __init__(self, title: str = "Myrmidon setup"):
        import cv2
        self.cv2 = cv2
        self.title = title
        self.opened = False

    def _line(self, img, text, y, scale, color, max_w):
        cv2 = self.cv2
        (tw, _), _ = cv2.getTextSize(text, FONT, scale, 2)
        if tw > max_w:
            scale *= max_w / tw
        cv2.putText(img, text, (16, y), FONT, scale, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, text, (16, y), FONT, scale, color, 2, cv2.LINE_AA)

    def show(self, frame, lines=(), big: str | None = None, color=(255, 255, 255)) -> str | None:
        """Draw and display one frame; returns a pressed key ('enter', 'esc', or a letter) or None."""
        cv2 = self.cv2
        img = cv2.flip(frame, 1) if frame is not None else np.full((480, 640, 3), 24, dtype=np.uint8)
        h, w = img.shape[:2]
        lines = [ln for ln in lines if ln is not None]
        if lines:
            band = img.copy()
            cv2.rectangle(band, (0, 0), (w, 30 * len(lines) + 18), (20, 20, 20), -1)
            img = cv2.addWeighted(band, 0.7, img, 0.3, 0)
            for i, text in enumerate(lines):
                self._line(img, text, 32 + 30 * i, 0.75, color if i == 0 else (235, 235, 235), w - 32)
        if big:
            (tw, th), _ = cv2.getTextSize(big, FONT, 3.0, 7)
            scale = 3.0 if tw < w - 40 else 3.0 * (w - 40) / tw
            (tw, th), _ = cv2.getTextSize(big, FONT, scale, 7)
            org = ((w - tw) // 2, min(h - 20, (h + th) // 2 + 60))
            cv2.putText(img, big, org, FONT, scale, (0, 0, 0), 14, cv2.LINE_AA)
            cv2.putText(img, big, org, FONT, scale, (80, 220, 255), 7, cv2.LINE_AA)
        if not self.opened:
            cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self.title, 960, 720)
            try:
                cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)
            except Exception:  # noqa: BLE001 - not every backend supports it
                pass
            self.opened = True
        cv2.imshow(self.title, img)
        k = cv2.waitKey(1)
        key = None
        if k not in (-1, 255) and k >= 0:
            k &= 0xFF
            key = {13: "enter", 10: "enter", 27: "esc", 32: "space"}.get(k, chr(k).lower() if 32 < k < 127 else None)
        ck = console_key()
        return ck or key

    def close(self) -> None:
        if self.opened:
            try:
                self.cv2.destroyWindow(self.title)
                self.cv2.waitKey(1)
            except Exception:  # noqa: BLE001
                pass
            self.opened = False
