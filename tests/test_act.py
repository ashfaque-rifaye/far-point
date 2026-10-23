from myrmidon.act import (
    Actuators,
    BrightnessController,
    DryRunBrightness,
    DryRunKeys,
    DryRunOverlay,
    DryRunTheme,
    DryRunWindow,
    RestoreJournal,
    ThemeController,
    ZoomController,
)


def test_non_allowlisted_process_gets_no_keys():
    a = Actuators.dry(process="ms-teams.exe")
    ok, msg, _ = a.zoom.step(+1)
    assert not ok and "not available" in msg
    assert a.zoom.keys.sent == []


def test_zoom_respects_typing_and_modifiers_and_caps():
    a = Actuators.dry(process="msedge.exe")
    a.zoom.window.idle = 0.1
    assert a.zoom.step(+1)[0] is False and a.zoom.keys.sent == []
    a.zoom.window.idle = 5
    a.zoom.keys.mods = True
    assert a.zoom.step(+1)[0] is False
    a.zoom.keys.mods = False
    for _ in range(5):
        a.zoom.step(+1)
    assert a.zoom.zoom_step() == 3 and len(a.zoom.keys.sent) == 3  # capped at +3


def test_restore_sends_exact_inverse_steps_per_window():
    a = Actuators.dry(process="msedge.exe")
    a.zoom.step(+1, steps=2)
    a.zoom.window.set("acrobat.exe", "paper.pdf")
    a.zoom.step(+1)
    a.zoom.window.set("notepad.exe", "notes")
    keys = a.zoom.keys
    keys.sent.clear()
    assert a.zoom.restore()
    assert sorted(keys.sent) == sorted([(-1, "msedge.exe"), (-1, "msedge.exe"), (-1, "acrobat.exe")])
    assert a.zoom.window.current.process == "notepad.exe"  # focus returned
    assert a.journal.entries() == {}


def test_brightness_and_theme_originals_restored():
    a = Actuators.dry(light=True, brightness=80)
    assert a.brightness.set_level(50)[0]
    assert a.brightness.set_level(40)[0]
    assert a.theme.set_dark(True)[0]
    assert a.state()["theme"] == "dark" and a.state()["brightness_pct"] == 40
    out = a.restore_all()
    assert out == {"zoom": True, "brightness": True, "theme": True}
    assert a.brightness.backend.level == 80 and a.theme.backend.value == 1
    hist = (list(a.brightness.backend.history), list(a.theme.backend.history))
    assert a.restore_all() == {"zoom": True, "brightness": True, "theme": True}  # idempotent
    assert (a.brightness.backend.history, a.theme.backend.history) == hist  # second call changed nothing


def test_journal_recover_after_simulated_crash(tmp_path):
    path = tmp_path / "restore.json"
    keys, win = DryRunKeys(), DryRunWindow("code.exe", "app.py")
    bright, theme = DryRunBrightness(70), DryRunTheme(light=True)
    j1 = RestoreJournal(path)
    crashed = Actuators(ZoomController(keys, win, j1), BrightnessController(bright, j1), ThemeController(theme, j1),
                        DryRunOverlay(), j1, dry_run=True)
    crashed.zoom.step(+1)
    crashed.brightness.set_level(30)
    crashed.theme.set_dark(True)
    assert set(RestoreJournal(path).entries()) == {f"zoom:{win.current.hwnd}", "brightness", "theme"}
    # "crash": no restore_all. A new run with a fresh journal object reads the file.
    keys.sent.clear()
    j2 = RestoreJournal(path)
    fresh = Actuators(ZoomController(keys, win, j2), BrightnessController(bright, j2), ThemeController(theme, j2),
                      DryRunOverlay(), j2, dry_run=True)
    out = fresh.recover()
    assert out == {"zoom": True, "brightness": True, "theme": True}
    assert keys.sent == [(-1, "code.exe")] and bright.level == 70 and theme.value == 1
    assert RestoreJournal(path).entries() == {}


def test_replay_env_changes_apply_only_when_trace_changes():
    a = Actuators.dry(light=True, brightness=60)
    a.observe_env({"process": "acrobat.exe", "title": "p.pdf", "idle_s": 30}, theme="light", brightness=60)
    a.theme.set_dark(True)
    a.observe_env({"process": "acrobat.exe", "title": "p.pdf", "idle_s": 30}, theme="light", brightness=60)
    assert a.state()["theme"] == "dark"  # Myrmidon's change sticks while the trace is unchanged
    assert a.state()["zoom_available"] is True
