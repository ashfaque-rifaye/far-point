"""Smoke test of the REAL actuators on this laptop. Everything it changes is restored.

  python scripts/smoke_actuators.py

- Zoom: real SendInput Ctrl+= / Ctrl+- into a test window this script creates and owns
  (it never touches your own windows), then restore with the inverse step.
- Brightness: -10 points via WMI, then restore.
- App theme: toggle AppsUseLightTheme, then restore.
- Overlay: a 3 s break overlay and a toast.

Exits 1 if any value after restore differs from before.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myrmidon.act import (  # noqa: E402
    BrightnessController,
    OverlayHost,
    RegistryTheme,
    RestoreJournal,
    ThemeController,
    WinKeys,
    WinWindow,
    WmiBrightness,
    ZoomController,
)

RUNTIME = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime"))


class ZoomProbe:
    """A small Tk window that zooms its own text on Ctrl+= / Ctrl+-, so the result is readable."""

    def __init__(self):
        self.level = 0
        self.hwnd = None
        self.ready = threading.Event()
        self._root = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.ready.wait(5)

    def _run(self):
        import tkinter as tk
        root = tk.Tk()
        root.title("Myrmidon actuator smoke test")
        root.geometry("420x160+200+200")
        root.attributes("-topmost", True)
        label = tk.Label(root, text="zoom 0", font=("Segoe UI", 14))
        label.pack(expand=True)

        def bump(d):
            self.level += d
            label.configure(text=f"zoom {self.level}", font=("Segoe UI", 14 + 2 * self.level))

        root.bind("<Control-equal>", lambda e: bump(+1))
        root.bind("<Control-plus>", lambda e: bump(+1))
        root.bind("<Control-minus>", lambda e: bump(-1))
        root.update()
        self.hwnd = int(root.wm_frame(), 16)
        self._root = root
        self.ready.set()
        root.mainloop()
        # Drop every Tk reference on this thread: Tcl must be torn down where it was created.
        self._root = None
        del label, root
        import gc
        gc.collect()

    def close(self):
        if self._root is not None:
            self._root.after(0, self._root.destroy)
        self.thread.join(2)


def wait_idle(win: WinWindow, s: float = 0.4, timeout: float = 10) -> None:
    end = time.time() + timeout
    while win.idle_s() < s and time.time() < end:
        time.sleep(0.1)


def main() -> int:
    journal = RestoreJournal(RUNTIME / "smoke" / "restore.json")
    report: dict = {}
    ok = True

    # Zoom ------------------------------------------------------------------------------
    win, keys = WinWindow(), WinKeys()
    original_fg = win.foreground()
    probe = ZoomProbe()
    zoom = ZoomController(keys, win, journal, allowlist={"python.exe", "pythonw.exe"})
    try:
        win.set_foreground(probe.hwnd)
        time.sleep(0.3)
        fg = win.foreground()
        report["zoom_window_in_front"] = bool(fg and fg.hwnd == probe.hwnd)
        before = probe.level
        wait_idle(win)
        applied, msg, net = zoom.step(+1)
        time.sleep(0.4)
        during = probe.level
        zoom.restore()
        time.sleep(0.4)
        after = probe.level
        report["zoom"] = {"before": before, "during": during, "after": after, "applied": applied, "message": msg}
        ok &= applied and during == before + 1 and after == before
    finally:
        probe.close()
        if original_fg is not None:
            win.set_foreground(original_fg.hwnd)

    # Brightness ------------------------------------------------------------------------
    bright = BrightnessController(WmiBrightness(), journal)
    b0 = bright.current(fresh=True)
    if b0 is None:
        report["brightness"] = "not available on this display"
    else:
        target = b0 - 10 if b0 >= 15 else b0 + 10
        bright.set_level(target)
        time.sleep(0.6)
        b1 = bright.current(fresh=True)
        bright.restore()
        time.sleep(0.6)
        b2 = bright.current(fresh=True)
        report["brightness"] = {"before": b0, "during": b1, "after": b2}
        ok &= b1 == target and b2 == b0

    # Theme -------------------------------------------------------------------------------
    theme = ThemeController(RegistryTheme(), journal)
    t0 = theme.theme()
    theme.set_dark(t0 == "light")
    time.sleep(0.8)
    t1 = theme.theme()
    theme.restore()
    time.sleep(0.3)
    t2 = theme.theme()
    report["theme"] = {"before": t0, "during": t1, "after": t2}
    ok &= t1 != t0 and t2 == t0

    # Overlay -------------------------------------------------------------------------------
    overlay = OverlayHost()
    overlay.show_break(3)
    for s in range(4):
        overlay.update(s)
        time.sleep(1)
    overlay.close()
    overlay.toast("Myrmidon smoke test: toast", seconds=2)
    time.sleep(2.5)
    overlay.shutdown()
    report["overlay"] = "shown 3 s, closed; toast shown 2 s"

    report["journal_after"] = journal.entries()
    ok &= report["journal_after"] == {}
    report["ok"] = bool(ok)
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
