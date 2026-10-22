"""Foreground-window context (Windows): which app, is it fullscreen, how long idle.

Window titles are read to categorise the app and are never stored or sent anywhere.
`capture_thumbnail` exists only for the optional vision mode and is never called in the
default text-only mode.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

ZOOM_ALLOWLIST = frozenset({
    "chrome.exe", "msedge.exe", "firefox.exe", "code.exe", "winword.exe", "notepad.exe",
    "acrobat.exe", "acrord32.exe", "sumatrapdf.exe",
})

DISPLAY_NAMES = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "code.exe": "VS Code", "notepad.exe": "Notepad", "notepad++.exe": "Notepad++",
    "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint", "outlook.exe": "Outlook",
    "acrobat.exe": "Acrobat Reader", "acrord32.exe": "Acrobat Reader", "sumatrapdf.exe": "SumatraPDF",
    "ms-teams.exe": "Microsoft Teams", "teams.exe": "Microsoft Teams", "zoom.exe": "Zoom",
    "vlc.exe": "VLC", "explorer.exe": "File Explorer", "windowsterminal.exe": "Terminal",
}

MEETING_PROCESSES = {"ms-teams.exe", "teams.exe", "zoom.exe", "cpthost.exe", "webexmta.exe", "ciscocollabhost.exe"}
MEETING_TITLES = ("microsoft teams", "zoom meeting", "webex", "google meet", "meet -", " - meet")
VIDEO_PROCESSES = {"vlc.exe", "mpv.exe", "wmplayer.exe", "video.ui.exe", "mpc-hc64.exe"}
VIDEO_TITLES = ("youtube", "netflix", "prime video", "disney+", "vlc media player", "twitch")
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}
EDITORS = {"code.exe", "notepad.exe", "notepad++.exe", "sublime_text.exe", "pycharm64.exe", "idea64.exe",
           "devenv.exe", "windowsterminal.exe", "cursor.exe"}
OFFICE = {"winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe", "onenote.exe"}
PDF = {"acrobat.exe", "acrord32.exe", "sumatrapdf.exe", "foxitpdfreader.exe"}

TYPING_IDLE_S = 1.5
SWITCH_RECENT_S = 5.0
IDLE_S = 10.0


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    process: str
    title: str
    rect: tuple[int, int, int, int]
    is_fullscreen: bool


def zoom_allowed(process: str) -> bool:
    return (process or "").lower() in ZOOM_ALLOWLIST


def display_name(process: str) -> str:
    p = (process or "").lower()
    if p in DISPLAY_NAMES:
        return DISPLAY_NAMES[p]
    stem = p[:-4] if p.endswith(".exe") else p
    return stem.replace("_", " ").title() or "unknown"


def categorize(process: str, title: str) -> str:
    p, t = (process or "").lower(), (title or "").lower()
    if p in MEETING_PROCESSES or any(k in t for k in MEETING_TITLES):
        return "meeting"
    if p in VIDEO_PROCESSES or any(k in t for k in VIDEO_TITLES):
        return "video"
    if p in PDF or t.endswith(".pdf") or ".pdf -" in t or ".pdf |" in t:
        return "pdf"
    if p in BROWSERS:
        return "browser"
    if p in EDITORS:
        return "editor"
    if p in OFFICE:
        return "office"
    return "other"


def activity_line(process: str, title: str, fullscreen: bool, idle_s: float, last_switch_s: float | None) -> tuple[str, bool]:
    """(Activity sentence in the S1 wording, interrupt_ok hint)."""
    cat = categorize(process, title)
    app = display_name(process)
    if cat == "meeting":
        return f"in a video call (foreground: {app})", False
    if cat == "video":
        if fullscreen:
            return f"watching a fullscreen video (foreground: {app})", False
        return f"watching a video (foreground: {app})", False
    if idle_s < TYPING_IDLE_S:
        return f"typing in a burst, last input {idle_s:.1f} s ago (foreground: {app})", False
    if last_switch_s is not None and last_switch_s < SWITCH_RECENT_S:
        return f"just switched windows to {app} ({cat})", True
    if idle_s >= IDLE_S:
        return f"idle for {idle_s:.0f} s (foreground: {app})", True
    return f"between tasks: no input for {idle_s:.0f} s (foreground: {app})", True


def context_dict(process: str, title: str, fullscreen: bool, idle_s: float, last_switch_s: float | None) -> dict:
    activity, ok = activity_line(process, title, fullscreen, idle_s, last_switch_s)
    return {
        "process": (process or "").lower(),
        "app_name": display_name(process),
        "category": categorize(process, title),
        "fullscreen": bool(fullscreen),
        "idle_s": float(idle_s),
        "activity": activity,
        "interrupt_ok_hint": ok,
        "zoom_allowed": zoom_allowed(process),
    }


# ---- Windows calls ----------------------------------------------------------------------

def foreground() -> WindowInfo | None:
    if sys.platform != "win32":
        return None
    import psutil
    import win32api
    import win32con
    import win32gui
    import win32process
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        process = psutil.Process(pid).name()
    except (psutil.Error, ValueError):
        process = ""
    title = win32gui.GetWindowText(hwnd)
    try:
        rect = win32gui.GetWindowRect(hwnd)
        mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        mrect = win32api.GetMonitorInfo(mon)["Monitor"]
        fullscreen = tuple(rect) == tuple(mrect)
    except Exception:  # noqa: BLE001 - a window can vanish between calls
        rect, fullscreen = (0, 0, 0, 0), False
    return WindowInfo(hwnd=int(hwnd), pid=int(pid), process=process, title=title, rect=tuple(rect),
                      is_fullscreen=fullscreen)


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_s() -> float:
    """Seconds since the last keyboard or mouse input (GetLastInputInfo)."""
    if sys.platform != "win32":
        return 60.0
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def window_exists(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    import win32gui
    return bool(win32gui.IsWindow(hwnd))


def capture_thumbnail(max_px: int = 448) -> str:
    """Screen thumbnail as base64 JPEG, kept in memory. ONLY used when vision is on."""
    import base64
    import io

    from PIL import ImageGrab
    img = ImageGrab.grab()
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ContextTracker:
    """Polls the foreground window and remembers when it last changed."""

    def __init__(self, clock):
        self.clock = clock
        self._hwnd: int | None = None
        self._switch_t: float | None = None
        self.last: WindowInfo | None = None

    def poll(self) -> dict:
        info = foreground()
        now = self.clock()
        if info is not None and info.hwnd != self._hwnd:
            if self._hwnd is not None:
                self._switch_t = now
            self._hwnd = info.hwnd
        self.last = info
        since = None if self._switch_t is None else now - self._switch_t
        if info is None:
            return context_dict("", "", False, idle_s(), since)
        ctx = context_dict(info.process, info.title, info.is_fullscreen, idle_s(), since)
        ctx["hwnd"] = info.hwnd
        return ctx
