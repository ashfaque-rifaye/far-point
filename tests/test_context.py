import pytest

from myrmidon.context import (
    ZOOM_ALLOWLIST,
    activity_line,
    categorize,
    context_dict,
    display_name,
    foreground,
    idle_s,
    zoom_allowed,
)


def test_categorize():
    assert categorize("ms-teams.exe", "Standup | Microsoft Teams") == "meeting"
    assert categorize("chrome.exe", "Meet - abc-defg-hij") == "meeting"
    assert categorize("msedge.exe", "Lo-fi beats - YouTube") == "video"
    assert categorize("Acrobat.exe", "paper.pdf - Adobe Acrobat Reader") == "pdf"
    assert categorize("msedge.exe", "report.pdf - Edge") == "pdf"
    assert categorize("msedge.exe", "Inbox") == "browser"
    assert categorize("Code.exe", "app.py - myrmidon") == "editor"
    assert categorize("WINWORD.EXE", "Doc1 - Word") == "office"
    assert categorize("explorer.exe", "Downloads") == "other"


def test_allowlist_is_case_insensitive():
    assert zoom_allowed("MSEDGE.EXE") and zoom_allowed("notepad.exe") and zoom_allowed("Acrobat.exe")
    assert not zoom_allowed("ms-teams.exe") and not zoom_allowed("")
    assert "winword.exe" in ZOOM_ALLOWLIST and display_name("Acrobat.exe") == "Acrobat Reader"


def test_activity_line_uses_s1_wording():
    assert activity_line("ms-teams.exe", "Call | Microsoft Teams", False, 30, None) == (
        "in a video call (foreground: Microsoft Teams)", False)
    assert activity_line("msedge.exe", "Film - YouTube", True, 30, None)[0].startswith("watching a fullscreen video")
    line, ok = activity_line("winword.exe", "Doc1 - Word", False, 0.4, None)
    assert line.startswith("typing in a burst") and ok is False
    assert activity_line("code.exe", "x", False, 3, 2.0) == ("just switched windows to VS Code (editor)", True)
    assert activity_line("code.exe", "x", False, 30, 120) == ("idle for 30 s (foreground: VS Code)", True)
    line, ok = activity_line("acrobat.exe", "a.pdf", False, 4, 60)
    assert line.startswith("between tasks") and ok is True
    ctx = context_dict("Acrobat.exe", "a.pdf - Adobe", False, 30, None)
    assert ctx["category"] == "pdf" and ctx["zoom_allowed"] and ctx["interrupt_ok_hint"] is True


@pytest.mark.live
def test_real_foreground_window():
    info = foreground()
    assert info is not None and info.process
    print(f"foreground process: {info.process} fullscreen={info.is_fullscreen} idle={idle_s():.1f}s")
