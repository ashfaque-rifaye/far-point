"""Reversible actuators: text zoom, screen brightness, app theme, break overlay, toasts.

Every change is journaled BEFORE it is made (`<runtime>/restore.json`), restored on exit
(`Actuators.restore_all`, also registered with atexit), and `Actuators.recover()` on the
next start restores whatever a crashed run left behind.

Zoom is restored with inverse key steps, not Ctrl+0: the user's original zoom is unknown,
and in VS Code Ctrl+0 focuses the sidebar. Word gets Ctrl+mouse-wheel because Ctrl+= is
subscript there.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import logging
import queue
import sys
import threading
import time
import zlib
from ctypes import wintypes
from pathlib import Path

from .context import ZOOM_ALLOWLIST, WindowInfo, display_name, foreground, idle_s, window_exists

log = logging.getLogger("myrmidon.act")

ZOOM_CAP_UP = 3
ZOOM_CAP_DOWN = -2


# ---- restore journal ----------------------------------------------------------------------

class RestoreJournal:
    """Originals of everything Myrmidon changed. `path=None` keeps it in memory (dry runs)."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self._data = {}

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def record(self, key: str, info: dict) -> None:
        """Keep the FIRST original for `key` (later changes must not overwrite it)."""
        with self._lock:
            if key not in self._data:
                self._data[key] = info
                self._save()

    def update(self, key: str, info: dict) -> None:
        with self._lock:
            self._data[key] = info
            self._save()

    def clear(self, key: str) -> None:
        with self._lock:
            if self._data.pop(key, None) is not None:
                self._save()

    def entries(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._data)


# ---- Win32 input ------------------------------------------------------------------------

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_WHEEL = 0x0800
VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN = 0x11, 0x10, 0x12, 0x5B, 0x5C
VK_OEM_PLUS, VK_OEM_MINUS = 0xBB, 0xBD
WHEEL_DELTA = 120


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _key(vk: int, up: bool = False) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=0,
                                                                   dwFlags=KEYEVENTF_KEYUP if up else 0,
                                                                   time=0, dwExtraInfo=0)))


def _wheel(delta: int) -> INPUT:
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(dx=0, dy=0, mouseData=delta & 0xFFFFFFFF,
                                                               dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0)))


class WinKeys:
    """Real keystrokes via SendInput."""

    def modifiers_down(self) -> bool:
        gks = ctypes.windll.user32.GetAsyncKeyState
        return any(gks(vk) & 0x8000 for vk in (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN))

    def zoom(self, direction: int, process: str) -> None:
        if process.lower() == "winword.exe":
            seq = [_key(VK_CONTROL), _wheel(WHEEL_DELTA * (1 if direction > 0 else -1)), _key(VK_CONTROL, True)]
        else:
            vk = VK_OEM_PLUS if direction > 0 else VK_OEM_MINUS
            seq = [_key(VK_CONTROL), _key(vk), _key(vk, True), _key(VK_CONTROL, True)]
        arr = (INPUT * len(seq))(*seq)
        sent = ctypes.windll.user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
        if sent != len(seq):
            raise OSError(f"SendInput sent {sent}/{len(seq)} events")
        time.sleep(0.05)


class WinWindow:
    def foreground(self) -> WindowInfo | None:
        return foreground()

    def idle_s(self) -> float:
        return idle_s()

    def exists(self, hwnd: int) -> bool:
        return window_exists(hwnd)

    def process_of(self, hwnd: int) -> str:
        import psutil
        import win32process
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return psutil.Process(pid).name()
        except Exception:  # noqa: BLE001 - window or process gone
            return ""

    def set_foreground(self, hwnd: int) -> bool:
        """Bring `hwnd` to the front (AttachThreadInput, so Windows' focus lock allows it)."""
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        fg = u32.GetForegroundWindow()
        if fg == hwnd:
            return True
        fg_tid = u32.GetWindowThreadProcessId(fg, None)
        me = k32.GetCurrentThreadId()
        attached = bool(fg_tid) and fg_tid != me and u32.AttachThreadInput(me, fg_tid, True)
        try:
            u32.ShowWindow(hwnd, 9 if u32.IsIconic(hwnd) else 5)  # SW_RESTORE / SW_SHOW
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(me, fg_tid, False)
        for _ in range(20):
            if u32.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.025)
        return False


# ---- zoom -----------------------------------------------------------------------------------

class ZoomController:
    def __init__(self, keys, window, journal: RestoreJournal, allowlist=ZOOM_ALLOWLIST, min_idle_s: float = 0.3):
        self.keys = keys
        self.window = window
        self.journal = journal
        self.allowlist = frozenset(p.lower() for p in allowlist)
        self.min_idle_s = min_idle_s
        self.net: dict[int, dict] = {}
        self._lock = threading.RLock()

    def _allowed(self, info: WindowInfo | None) -> bool:
        return info is not None and info.process.lower() in self.allowlist

    def available(self) -> bool:
        return self._allowed(self.window.foreground())

    def zoom_step(self, hwnd: int | None = None) -> int:
        with self._lock:
            if hwnd is None:
                info = self.window.foreground()
                hwnd = info.hwnd if info else None
            return int(self.net.get(hwnd, {}).get("steps", 0)) if hwnd is not None else 0

    def can_step(self, direction: int) -> bool:
        info = self.window.foreground()
        if not self._allowed(info):
            return False
        cur = self.zoom_step(info.hwnd)
        return (cur < ZOOM_CAP_UP) if direction > 0 else (cur > ZOOM_CAP_DOWN)

    def step(self, direction: int, steps: int = 1) -> tuple[bool, str, int]:
        """Returns (applied, message, net_steps_after)."""
        with self._lock:
            info = self.window.foreground()
            if not self._allowed(info):
                name = display_name(info.process) if info else "this app"
                return False, f"Zoom control is not available for {name}.", 0
            cur = int(self.net.get(info.hwnd, {}).get("steps", 0))
            target = max(ZOOM_CAP_DOWN, min(ZOOM_CAP_UP, cur + (1 if direction > 0 else -1) * max(1, int(steps))))
            n = abs(target - cur)
            if n == 0:
                return False, f"Myrmidon zoom is already at its limit ({cur:+d}).", cur
            if self.keys.modifiers_down():
                return False, "A modifier key is held down, so no keys were sent.", cur
            if self.window.idle_s() < self.min_idle_s:
                return False, "You are typing, so no keys were sent.", cur
            key = f"zoom:{info.hwnd}"
            rec = {"hwnd": info.hwnd, "pid": info.pid, "process": info.process}
            self.journal.update(key, {**rec, "steps": target})  # journal BEFORE sending
            sign = 1 if target > cur else -1
            sent = 0
            for _ in range(n):
                now = self.window.foreground()
                if now is None or now.hwnd != info.hwnd:
                    break  # the user switched windows: stop
                self.keys.zoom(sign, info.process)
                sent += 1
            new = cur + sign * sent
            if new == 0:
                self.net.pop(info.hwnd, None)
                self.journal.clear(key)
            else:
                self.net[info.hwnd] = {**rec, "steps": new}
                self.journal.update(key, {**rec, "steps": new})
            if sent == 0:
                return False, "The window changed before keys were sent.", cur
            verb = "enlarged" if sign > 0 else "reduced"
            return True, f"Text {verb} {sent} step{'s' if sent > 1 else ''} in {display_name(info.process)}.", new

    def adopt(self, entries: dict[int, dict]) -> None:
        """Take over zoom entries from a crash journal."""
        with self._lock:
            self.net.update(entries)

    def restore(self) -> bool:
        """Send the inverse steps to every window Myrmidon zoomed, then refocus."""
        with self._lock:
            if not any(st.get("steps") for st in self.net.values()):
                return True
            orig = self.window.foreground()
            ok = True
            for hwnd, st in list(self.net.items()):
                steps = int(st.get("steps", 0))
                key = f"zoom:{hwnd}"
                if steps == 0 or not self.window.exists(hwnd):
                    self.net.pop(hwnd, None)
                    self.journal.clear(key)
                    continue
                if not self.window.set_foreground(hwnd):
                    ok = False
                    continue
                for _ in range(abs(steps)):
                    self.keys.zoom(-1 if steps > 0 else 1, st.get("process", ""))
                self.net.pop(hwnd, None)
                self.journal.clear(key)
            if orig is not None and self.window.exists(orig.hwnd):
                self.window.set_foreground(orig.hwnd)
            return ok


# ---- brightness ---------------------------------------------------------------------------

class WmiBrightness:
    """Internal-panel brightness via WMI. External monitors are not supported."""

    def _wmi(self):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()  # per thread
        return win32com.client.GetObject("winmgmts:\\\\.\\root\\WMI")

    def get(self) -> int | None:
        try:
            for m in self._wmi().InstancesOf("WmiMonitorBrightness"):
                return int(m.CurrentBrightness)
        except Exception:  # noqa: BLE001 - no WMI brightness on this display
            return None
        return None

    def set(self, level: int) -> None:
        for m in self._wmi().InstancesOf("WmiMonitorBrightnessMethods"):
            params = m.Methods_("WmiSetBrightness").InParameters.SpawnInstance_()
            params.Properties_.Item("Timeout").Value = 1
            params.Properties_.Item("Brightness").Value = int(level)
            m.ExecMethod_("WmiSetBrightness", params)
            return
        raise OSError("no WmiMonitorBrightnessMethods instance")


class BrightnessController:
    CACHE_S = 5.0

    def __init__(self, backend, journal: RestoreJournal, clock=time.monotonic):
        self.backend = backend
        self.journal = journal
        self.clock = clock
        self._cache: tuple[float, int | None] | None = None
        self._lock = threading.RLock()

    def current(self, fresh: bool = False) -> int | None:
        with self._lock:
            now = self.clock()
            if fresh or self._cache is None or now - self._cache[0] > self.CACHE_S:
                self._cache = (now, self.backend.get())
            return self._cache[1]

    def available(self) -> bool:
        return self.current() is not None

    def set_level(self, level_pct: int) -> tuple[bool, str]:
        with self._lock:
            cur = self.current(fresh=True)
            if cur is None:
                return False, "Screen brightness is not adjustable on this display."
            level_pct = max(5, min(100, int(level_pct)))
            if level_pct == cur:
                return False, f"Screen brightness is already {cur}%."
            self.journal.record("brightness", {"level": cur})  # first original only
            self.backend.set(level_pct)
            self._cache = (self.clock(), level_pct)
            return True, f"Screen brightness {cur}% -> {level_pct}%."

    def restore(self) -> bool:
        with self._lock:
            orig = self.journal.entries().get("brightness")
            if not orig:
                return True
            try:
                self.backend.set(int(orig["level"]))
            except Exception as e:  # noqa: BLE001
                log.warning("brightness restore failed: %s", e)
                return False
            self.journal.clear("brightness")
            self._cache = None
            return True


# ---- theme ----------------------------------------------------------------------------------

class RegistryTheme:
    KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    VALUE = "AppsUseLightTheme"

    def get(self) -> int | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as k:
                return int(winreg.QueryValueEx(k, self.VALUE)[0])
        except OSError:
            return None

    def set(self, value: int) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, self.VALUE, 0, winreg.REG_DWORD, int(value))
        result = ctypes.c_size_t(0)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, ctypes.c_wchar_p("ImmersiveColorSet"),
                                                 0x0002, 200, ctypes.byref(result))


class ThemeController:
    def __init__(self, backend, journal: RestoreJournal):
        self.backend = backend
        self.journal = journal
        self._lock = threading.RLock()

    def theme(self) -> str | None:
        v = self.backend.get()
        return None if v is None else ("light" if v else "dark")

    def available(self) -> bool:
        return self.backend.get() is not None

    def set_dark(self, on: bool = True) -> tuple[bool, str]:
        with self._lock:
            cur = self.backend.get()
            if cur is None:
                return False, "The app theme cannot be changed here."
            want = 0 if on else 1
            if cur == want:
                return False, f"The app theme is already {'dark' if on else 'light'}."
            self.journal.record("theme", {"AppsUseLightTheme": cur})
            self.backend.set(want)
            return True, f"Switched apps to {'dark' if on else 'light'} mode."

    def restore(self) -> bool:
        with self._lock:
            orig = self.journal.entries().get("theme")
            if not orig:
                return True
            try:
                self.backend.set(int(orig["AppsUseLightTheme"]))
            except Exception as e:  # noqa: BLE001
                log.warning("theme restore failed: %s", e)
                return False
            self.journal.clear("theme")
            return True


# ---- overlay (Tk, one dedicated thread) ---------------------------------------------------

class OverlayHost:
    """Topmost break overlay and small toasts. All Tk work happens on one thread."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="myrmidon-overlay", daemon=True)
                self._thread.start()

    def available(self) -> bool:
        return sys.platform == "win32"

    def show_break(self, target_s: float, on_skip=None) -> None:
        self._ensure()
        self._q.put(("break", float(target_s), on_skip))

    def update(self, looking_away_s: float) -> None:
        self._q.put(("update", float(looking_away_s)))

    def close(self) -> None:
        self._q.put(("close",))

    def toast(self, text: str, seconds: float = 6.0) -> None:
        self._ensure()
        self._q.put(("toast", text, float(seconds)))

    def shutdown(self) -> None:
        if self._thread and self._thread.is_alive():
            self._q.put(("quit",))
            self._thread.join(2.0)

    def _run(self) -> None:  # pragma: no cover - needs a display
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        state: dict = {"win": None, "label": None, "target": 20.0}

        def close_break():
            if state["win"] is not None:
                state["win"].destroy()
                state["win"] = None

        def poll():
            try:
                while True:
                    msg = self._q.get_nowait()
                    kind = msg[0]
                    if kind == "quit":
                        close_break()
                        root.destroy()
                        return
                    if kind == "break":
                        close_break()
                        _, target, on_skip = msg
                        state["target"] = target
                        w = tk.Toplevel(root)
                        w.overrideredirect(True)
                        w.attributes("-topmost", True)
                        w.attributes("-alpha", 0.9)
                        w.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
                        w.configure(bg="#0b1d2a")
                        tk.Label(w, text="Look at something about 6 m (20 ft) away", fg="#e8f1f8", bg="#0b1d2a",
                                 font=("Segoe UI", 34)).pack(expand=True, pady=(0, 10))
                        lab = tk.Label(w, text=f"0 / {target:.0f} s looking away", fg="#9fd3ff", bg="#0b1d2a",
                                       font=("Segoe UI", 24))
                        lab.pack()
                        tk.Label(w, text="The camera counts the seconds you look away. Esc to skip.", fg="#7d93a6",
                                 bg="#0b1d2a", font=("Segoe UI", 14)).pack(expand=True)
                        if on_skip is not None:
                            w.bind("<Escape>", lambda e: on_skip())
                        w.focus_force()
                        state["win"], state["label"] = w, lab
                    elif kind == "update" and state["win"] is not None:
                        state["label"].configure(text=f"{msg[1]:.0f} / {state['target']:.0f} s looking away")
                    elif kind == "close":
                        close_break()
                    elif kind == "toast":
                        _, text, seconds = msg
                        t = tk.Toplevel(root)
                        t.overrideredirect(True)
                        t.attributes("-topmost", True)
                        t.attributes("-alpha", 0.95)
                        t.configure(bg="#13293d")
                        tk.Label(t, text=text, fg="#ffffff", bg="#13293d", font=("Segoe UI", 12), wraplength=360,
                                 justify="left", padx=16, pady=12).pack()
                        t.update_idletasks()
                        x = root.winfo_screenwidth() - t.winfo_width() - 24
                        y = root.winfo_screenheight() - t.winfo_height() - 72
                        t.geometry(f"+{x}+{y}")
                        t.after(int(seconds * 1000), t.destroy)
            except queue.Empty:
                pass
            root.after(50, poll)

        root.after(50, poll)
        root.mainloop()
        # Tear Tcl down on the thread that created it (avoids Tcl_AsyncDelete at exit).
        state.clear()
        del root
        import gc
        gc.collect()


# ---- dry-run backends (replay and tests) ----------------------------------------------------

class DryRunKeys:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.mods = False

    def modifiers_down(self) -> bool:
        return self.mods

    def zoom(self, direction: int, process: str) -> None:
        self.sent.append((direction, process))


class DryRunWindow:
    """A simulated foreground window, driven by replay context."""

    def __init__(self, process: str = "", title: str = ""):
        self.windows: dict[int, WindowInfo] = {}
        self.current: WindowInfo | None = None
        self.idle = 5.0
        if process:
            self.set(process, title)

    @staticmethod
    def hwnd_for(process: str) -> int:
        return zlib.crc32(process.lower().encode()) & 0x7FFFFFFF or 1

    def set(self, process: str, title: str = "", idle: float | None = None) -> None:
        hwnd = self.hwnd_for(process)
        info = WindowInfo(hwnd=hwnd, pid=hwnd, process=process, title=title, rect=(0, 0, 0, 0), is_fullscreen=False)
        self.windows[hwnd] = info
        self.current = info
        if idle is not None:
            self.idle = idle

    def foreground(self) -> WindowInfo | None:
        return self.current

    def idle_s(self) -> float:
        return self.idle

    def exists(self, hwnd: int) -> bool:
        return hwnd in self.windows

    def process_of(self, hwnd: int) -> str:
        return self.windows[hwnd].process if hwnd in self.windows else ""

    def set_foreground(self, hwnd: int) -> bool:
        if hwnd in self.windows:
            self.current = self.windows[hwnd]
            return True
        return False


class DryRunBrightness:
    def __init__(self, level: int | None = 60):
        self.level = level
        self.history: list[int] = []

    def get(self) -> int | None:
        return self.level

    def set(self, level: int) -> None:
        self.level = int(level)
        self.history.append(int(level))


class DryRunTheme:
    def __init__(self, light: bool = True):
        self.value: int | None = 1 if light else 0
        self.history: list[int] = []

    def get(self) -> int | None:
        return self.value

    def set(self, value: int) -> None:
        self.value = int(value)
        self.history.append(int(value))


class DryRunOverlay:
    def __init__(self):
        self.calls: list[tuple] = []

    def available(self) -> bool:
        return True

    def show_break(self, target_s, on_skip=None):
        self.calls.append(("break", target_s))
        self.on_skip = on_skip

    def update(self, looking_away_s):
        self.calls.append(("update", looking_away_s))

    def close(self):
        self.calls.append(("close",))

    def toast(self, text, seconds=6.0):
        self.calls.append(("toast", text))

    def shutdown(self):
        self.calls.append(("shutdown",))


# ---- bundle -----------------------------------------------------------------------------------

class Actuators:
    def __init__(self, zoom: ZoomController, brightness: BrightnessController, theme: ThemeController,
                 overlay, journal: RestoreJournal, dry_run: bool):
        self.zoom = zoom
        self.brightness = brightness
        self.theme = theme
        self.overlay = overlay
        self.journal = journal
        self.dry_run = dry_run
        self.restored = False
        self._lock = threading.Lock()
        self._env_seen: dict[str, object] = {}
        atexit.register(self.restore_all)

    @classmethod
    def real(cls, runtime_dir: Path) -> "Actuators":
        journal = RestoreJournal(Path(runtime_dir) / "restore.json")
        return cls(ZoomController(WinKeys(), WinWindow(), journal), BrightnessController(WmiBrightness(), journal),
                   ThemeController(RegistryTheme(), journal), OverlayHost(), journal, dry_run=False)

    @classmethod
    def dry(cls, light: bool = True, brightness: int | None = 60, process: str = "") -> "Actuators":
        journal = RestoreJournal(None)
        return cls(ZoomController(DryRunKeys(), DryRunWindow(process), journal),
                   BrightnessController(DryRunBrightness(brightness), journal),
                   ThemeController(DryRunTheme(light), journal), DryRunOverlay(), journal, dry_run=True)

    def available(self) -> dict[str, bool]:
        return {
            "zoom": self.zoom.available(),
            "brightness": self.brightness.available(),
            "theme": self.theme.available(),
            "overlay": self.overlay.available(),
        }

    def state(self) -> dict:
        return {
            "zoom_available": self.zoom.available(),
            "zoom_step": self.zoom.zoom_step(),
            "theme": self.theme.theme() or "light",
            "brightness_pct": self.brightness.current(),
        }

    def observe_env(self, ctx: dict | None = None, theme: str | None = None, brightness: int | None = None) -> None:
        """Replay only: a trace row describes the simulated desktop. A value is applied when the
        TRACE changes it (the simulated user did it); Myrmidon's own changes stick otherwise."""
        if not self.dry_run:
            return
        if ctx:
            self.zoom.window.set(ctx.get("process", ""), ctx.get("title", ""), idle=ctx.get("idle_s"))
        if theme is not None and self._env_seen.get("theme") != theme:
            self._env_seen["theme"] = theme
            self.theme.backend.value = 1 if theme == "light" else 0
        if brightness is not None and self._env_seen.get("brightness") != brightness:
            self._env_seen["brightness"] = brightness
            self.brightness.backend.level = int(brightness)
            self.brightness._cache = None

    def recover(self) -> dict:
        """Restore what a crashed run left in the journal. Call once at startup."""
        entries = self.journal.entries()
        if not entries:
            return {}
        zooms = {}
        for key, st in entries.items():
            if key.startswith("zoom:"):
                hwnd = int(st.get("hwnd", key.split(":", 1)[1]))
                same_app = self.zoom.window.process_of(hwnd).lower() == str(st.get("process", "")).lower()
                if self.zoom.window.exists(hwnd) and same_app:  # hwnds get reused: check the app too
                    zooms[hwnd] = st
                else:
                    self.journal.clear(key)
        self.zoom.adopt(zooms)
        out = {"zoom": self.zoom.restore(), "brightness": self.brightness.restore(), "theme": self.theme.restore()}
        log.info("recovered from crash journal: %s", out)
        return out

    def restore_all(self) -> dict:
        with self._lock:
            out = {"zoom": self.zoom.restore(), "brightness": self.brightness.restore(), "theme": self.theme.restore()}
            try:
                self.overlay.close()
            except Exception:  # noqa: BLE001
                pass
            self.restored = all(out.values())
            if not self.journal.entries():
                log.info("restored: nothing left to undo")
            return out
