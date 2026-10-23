"""Live smoke test of the real path on this laptop. Prints a JSON report; exits 1 on failure.

  python scripts/smoke_live.py

1. Decider: /health, then the real reflex loop's requests (8 rule nouls + interrupt_ok each).
2. Bedrock: one real Coach report through Amazon Nova Lite (text and numbers only).
3. Camera: the real LiveSource for ~12 s. Reports frames, faces and distance readings.
4. Adaptations: the real reflex loop (real Decider, real Strands tools, REAL actuators) runs on
   recorded numbers, because a person cannot be scripted:
   a. bright room, dim screen, squinting -> brighten_screen via WMI (needs no window focus),
      then the squint relaxes -> verification recorded;
   b. lean in to 27 cm while a test window this script owns is in front -> enlarge_text via
      SendInput -> the window's zoom goes 0 -> 1 -> verification recorded. Skipped (and said so)
      when Windows will not give the test window focus (locked screen, shell flyout open).
5. Restore: Runtime.stop() restores everything. Brightness, app theme and the test window's
   zoom must be back to their starting values and the restore journal empty.

Runtime data goes to <MYRMIDON_RUNTIME>/smoke-live, never the live profile.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from smoke_actuators import ZoomProbe, wait_idle  # noqa: E402

from myrmidon.act import ZOOM_ALLOWLIST, RegistryTheme, WinWindow, WmiBrightness  # noqa: E402
from myrmidon.config import Settings  # noqa: E402
from myrmidon.contract import errors  # noqa: E402
from myrmidon.doctrine import Limits  # noqa: E402
from myrmidon.runtime import Runtime  # noqa: E402
from myrmidon.signals import SignalTracker  # noqa: E402
from myrmidon.sources import LiveSource  # noqa: E402

RUNTIME = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime"))


def segment(t0: float, dur: float, **kw):
    base = {"face": True, "distance_cm": 52.0, "squint_ratio": 0.96, "yaw": 0.0, "pitch": 0.0, "luma": 120.0,
            "process": "acrobat.exe", "title": "paper.pdf - Adobe Acrobat Reader", "idle_s": 30.0,
            "fullscreen": False, "theme": None, "brightness": None}
    base.update(kw)
    t = t0
    for _ in range(int(dur * 10)):
        t += 0.1
        yield {**base, "t": round(t, 2), "ear": round(0.28 * base["squint_ratio"], 4)}


def summarize(events, tool):
    acts = [e["data"] for e in events if e["type"] == "action" and e["data"]["tool"] == tool]
    a = next((x for x in acts if x["status"] == "done"), acts[0] if acts else None)
    if a is None:
        return None
    dec = next((e["data"] for e in events if e["type"] == "decision" and e["data"]["id"] == a["decision_id"]), {})
    ver = next((e["data"] for e in events if e["type"] == "verification" and e["data"]["action_id"] == a["id"]), None)
    return {"action": {k: a[k] for k in ("id", "status", "message")}, "rule_ref": dec.get("rule_ref"),
            "decider_latency_ms": dec.get("latency_ms"), "decider_source": dec.get("source"),
            "verification": {k: ver[k] for k in ("outcome", "before", "after", "window_s")} if ver else None}


def main() -> int:
    report: dict = {}
    ok = True
    scratch = RUNTIME / "smoke-live"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "none.jsonl").write_text('{"kind":"header","version":1}\n')
    theme0, bright0 = RegistryTheme().get(), WmiBrightness().get()
    report["start"] = {"AppsUseLightTheme": theme0, "brightness_pct": bright0}

    rt = Runtime(Settings(mode="replay", actuate=True, runtime_dir=scratch, trace=scratch / "none.jsonl"))
    events: list[dict] = []
    rt.bus.add_listener(events.append)

    # 1. Decider
    rt._poll_health()
    report["decider"] = {"status": rt.decider_status, "model": rt.decider_model, "device": rt.decider_device}
    ok &= rt.decider_status == "ready"

    # 2. Bedrock coach
    t0 = time.time()
    rep = rt.coach.report("today") if rt.bedrock_status == "ready" else None
    report["bedrock_report"] = ({"starts_with_disclaimer": rep["markdown"].startswith(
                                    "> Behavioral observations, not a diagnosis."),
                                 "seconds": round(time.time() - t0, 1), "chars": len(rep["markdown"]),
                                 "tokens": rt.stats.get("bedrock_tokens"), "model": rep["model"]}
                                if rep else f"not run (Bedrock {rt.bedrock_status})")
    ok &= bool(rep)

    # 3. Camera
    tracker = SignalTracker()
    distances: list[float] = []
    src = LiveSource(tracker, lambda t: distances.append(tracker.distance_cm) if tracker.face else None)
    src.start()
    time.sleep(12)
    src.stop()
    distinct = sorted({round(d, 1) for d in distances if d is not None})
    report["camera"] = {"frames": src.frames, "frames_with_face": src.faces, "distinct_distances": len(distinct),
                        "distance_cm_range": [distinct[0], distinct[-1]] if distinct else None,
                        "note": "frames stayed in memory; none written to disk"}
    ok &= src.frames > 0

    # 4a. brighten_screen on recorded numbers (real WMI)
    win = WinWindow()
    original_fg = win.foreground()
    last = {"process": None}
    if bright0 is not None and bright0 < 60:
        d = rt.store.save_draft("smoke test", rt.store.active.profile, Limits(bright_pct_low=bright0 + 5),
                                rt.store.active.rules)
        rt.store.approve(d.version)
        for row in segment(0, 6):
            rt.source.feed(row, last)
        for row in list(segment(6, 8, luma=210.0, squint_ratio=0.70)) + list(segment(14, 30, luma=210.0)):
            rt.source.feed(row, last)
        report["brighten_screen"] = summarize(events, "brighten_screen")
        report["brightness_during"] = WmiBrightness().get()
        b = report["brighten_screen"]
        ok &= bool(b and b["action"]["status"] == "done" and b["verification"])
    else:
        report["brighten_screen"] = "skipped: no adjustable display or brightness already >= 60%"

    # 4b. enlarge_text on recorded numbers, into a test window this script owns (real SendInput)
    rt.actuators.zoom.allowlist = frozenset(ZOOM_ALLOWLIST | {"python.exe"})
    probe = ZoomProbe()
    try:
        focused = win.set_foreground(probe.hwnd)
        fg = win.foreground()
        report["zoom_test_window_in_front"] = bool(focused)
        if not focused:
            report["enlarge_text"] = (f"skipped: Windows kept {fg.process if fg else 'nothing'} in front "
                                      "(locked screen or shell flyout); rerun at an unlocked desktop")
        else:
            wait_idle(win)
            for row in list(segment(50, 6)) + list(segment(56, 14, distance_cm=27.0, squint_ratio=0.8)) \
                    + list(segment(70, 35, distance_cm=45.0)):
                if int(row["t"] * 10) % 25 == 0:
                    win.set_foreground(probe.hwnd)
                rt.source.feed(row, last)
            report["enlarge_text"] = summarize(events, "enlarge_text")
            report["enlarge_text_window_zoom_after_action"] = probe.level
            e = report["enlarge_text"]
            ok &= bool(e and e["action"]["status"] == "done" and probe.level == 1 and e["verification"])

        # 5. Restore on exit
        rt.stop()
        time.sleep(0.5)
        report["restore"] = {"runtime_restored": rt.restored, "test_window_zoom_after_stop": probe.level,
                             "brightness_after_stop": WmiBrightness().get(),
                             "theme_unchanged": RegistryTheme().get() == theme0,
                             "brightness_unchanged": WmiBrightness().get() == bright0,
                             "journal_after_stop": rt.actuators.journal.entries()}
        r = report["restore"]
        ok &= probe.level == 0 and r["theme_unchanged"] and r["brightness_unchanged"] and r["journal_after_stop"] == {}
    finally:
        probe.close()
        if original_fg is not None:
            win.set_foreground(original_fg.hwnd)
    decs = [e["data"] for e in events if e["type"] == "decision"]
    report["decisions"] = {"count": len(decs), "fallback": sum(d["source"] == "fallback" for d in decs),
                           "p50_ms": rt.stats.snapshot()["decider_p50_ms"]}
    report["events"] = {"count": len(events), "schema_errors": [e["type"] for e in events if errors(e, "ServerEvent")]}
    ok &= not report["events"]["schema_errors"]
    report["ok"] = bool(ok)
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
