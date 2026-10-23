"""Guided human session (about 8-10 minutes). Run it through scripts/human_session.ps1.

  A  camera check + calibration at a measured distance            -> results/human_a_camera.json
  B  live lean-in trial in Edge: real Decider, real enlarge_text,
     verification, everything restored                            -> results/human_b_lean_in.json
  C  S2 labeled capture (eval/spike_s2.py capture), Decider -> -Vision -> results/s2_capture.json, human_c_capture.json
  D  S2 scoring + vision on/off decision, Decider back to text     -> results/s2_score.json, s2_decision.json, human_d_s2.json
  E  rulebook approval in the dashboard (only if web/dist exists)  -> results/human_e_approval.json

Every part waits for ENTER first (S skips it, Q quits) and can be re-run alone:
  .\\scripts\\human_session.ps1 -Parts b
Nothing here uploads anything. Camera frames stay in memory, except the S2 labeled capture,
which goes to FARPOINT_RUNTIME/s2-frames (outside the repo) and can be deleted after scoring.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import decider_ctl  # noqa: E402

RUNTIME = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))
RESULTS = ROOT / "results"
SESSION_DIR = RUNTIME / "human-session"
PROGRESS = SESSION_DIR / "progress.jsonl"
PY = sys.executable
T0 = time.time()


# ---- small helpers ------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def progress(part: str, event: str, **kw) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now_iso(), "part": part, "event": event, **kw}) + "\n")


def save(name: str, data: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(data, indent=2), encoding="utf-8")
    progress(data.get("part", "?"), "saved", file=name, status=data.get("status"))


def beep(n: int = 1) -> None:
    try:
        import winsound
        for _ in range(n):
            winsound.Beep(880, 140)
            time.sleep(0.06)
    except (ImportError, RuntimeError):
        pass


def elapsed() -> str:
    s = int(time.time() - T0)
    return f"{s // 60}:{s % 60:02d}"


def header(part: str, title: str, about: str) -> None:
    print("\n" + "=" * 72)
    print(f" PART {part.upper()}: {title}   (about {about}; session time {elapsed()})")
    print("=" * 72, flush=True)


def get_key(keys: set[str], default: str | None = None) -> str:
    import msvcrt
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        k = "enter" if ch in ("\r", "\n") else ch.lower()
        if k == "enter" and default is not None:
            return default
        if k in keys:
            return k


def ask(prompt: str, keys: set[str], default: str | None = None) -> str:
    print(prompt, end=" ", flush=True)
    k = get_key(keys, default)
    print(k.upper() if k != "enter" else "")
    return k


def start_gate(part: str) -> str:
    """ENTER = go, S = skip, Q = quit."""
    k = ask(f"Press ENTER to start part {part.upper()}, S to skip it, Q to quit:", {"enter", "s", "q"})
    progress(part, {"enter": "start", "s": "skipped", "q": "quit"}[k])
    return k


# ---- A: camera check + calibration ---------------------------------------------------------

DISTANCES = {"a": (29.7, "the long side of one A4 sheet"), "b": (59.4, "two A4 sheets end to end"),
             "4": (40.0, "40 cm with a ruler or tape"), "5": (50.0, "50 cm with a ruler or tape"),
             "6": (60.0, "60 cm with a ruler or tape")}


def part_a(args) -> dict:
    from farpoint.preview import Preview
    from farpoint.sense import CALIBRATION_PATH, Calibration, FaceSensor, focal_length_px, frame_luma, open_camera
    from farpoint.signals import LOOK_PITCH_DEG, LOOK_YAW_DEG

    res: dict = {"part": "a", "date": now_iso(), "status": "failed"}
    try:
        old = Calibration.load()
    except (OSError, ValueError):
        old = None
    sensor = FaceSensor()
    cap = open_camera(args.camera)
    pv = Preview("Far Point setup - camera (press keys here or in the console)")

    def frame():
        ok, f = cap.read()
        return f if ok else None

    def run_for(seconds, lines_fn, big_fn=None, calib=None, on_reading=None):
        end = time.time() + seconds
        while time.time() < end:
            f = frame()
            if f is None:
                continue
            r = sensor.read(f, calib)
            if on_reading:
                on_reading(r)
            pv.show(f, lines_fn(r, end - time.time()), big_fn(r, end - time.time()) if big_fn else None)

    try:
        # 1. live check
        seen, total, lumas = 0, 0, []
        print("A camera window opened. Sit facing the screen with your face in the middle of the picture.")
        print("Press ENTER (in the camera window or here) when the window says 'face: found'. S skips.")
        while True:
            f = frame()
            if f is None:
                continue
            r = sensor.read(f, old)
            luma = frame_luma(f)
            total += 1
            seen += r is not None
            lumas.append(luma)
            dist = f"{r.distance_cm:.0f} cm (old calibration)" if (r and r.distance_cm) else "-"
            lines = ["PART A - CAMERA CHECK",
                     f"face: {'found' if r else 'NOT found'}   light: {luma:.0f}/255"
                     + ("  (too dark: turn on a light facing you)" if luma < 50 else ""),
                     f"distance: {dist}",
                     "ENTER = continue    S = skip this part"]
            k = pv.show(f, lines, color=(120, 255, 120) if r else (80, 80, 255))
            if k == "s":
                res["status"] = "skipped"
                return res
            if k == "enter" and r is not None:
                break
        res["camera"] = {"frames_checked": total, "face_rate": round(seen / max(1, total), 2),
                         "mean_luma": round(statistics.mean(lumas[-60:]), 1)}

        # 2. distance method
        print("\nChoose how you set your eye-to-webcam distance (press the key in either window):")
        for k, (cm, how) in DISTANCES.items():
            print(f"   {k.upper()} = {how} ({cm:g} cm)")
        choice = None
        while choice is None:
            f = frame()
            if f is None:
                continue
            k = pv.show(f, ["HOW WILL YOU SET THE DISTANCE (eyes to webcam)?",
                            "A = one A4 sheet, long side (29.7 cm)",
                            "B = two A4 sheets end to end (59.4 cm)",
                            "4 / 5 / 6 = 40 / 50 / 60 cm with a ruler or tape",
                            "press the key"])
            if k in DISTANCES:
                choice = k
        cm, how = DISTANCES[choice]
        print(f"   -> {how}: {cm:g} cm")

        # 3. measure
        while True:
            print(f"\nHold the sheet or ruler from the webcam to your eye ({cm:g} cm), then lower it and hold still,")
            print("looking at the screen with relaxed eyes. Press ENTER when you are in place.")
            while True:
                f = frame()
                if f is None:
                    continue
                k = pv.show(f, [f"SET {cm:g} cm FROM THE WEBCAM TO YOUR EYES",
                                "Hold the sheet/ruler from the webcam to your eye, then lower it.",
                                "Keep still, look at the screen, eyes relaxed.",
                                "ENTER = I am in place"])
                if k == "enter":
                    break
            run_for(3, lambda r, left: ["HOLD STILL, EYES RELAXED"], lambda r, left: str(int(left) + 1))
            beep(1)
            iris, ears = [], []
            deadline = time.time() + 20
            while len(iris) < 60 and time.time() < deadline:
                f = frame()
                if f is None:
                    continue
                r = sensor.read(f)
                if r:
                    iris.append(r.iris_px)
                    ears.append(r.ear)
                pv.show(f, ["MEASURING... hold still", f"{len(iris)}/60 frames with your face"], "HOLD")
            beep(2)
            if len(iris) >= 20:
                break
            print("Not enough frames with your face (light, or face out of the picture). R = retry, S = skip.")
            if ask("R/S:", {"r", "s"}) == "s":
                res["status"] = "skipped"
                return res
        calib = Calibration(focal_px=focal_length_px(statistics.median(iris), cm),
                            ear_baseline=statistics.median(ears))
        if CALIBRATION_PATH.exists():
            shutil.copy2(CALIBRATION_PATH, CALIBRATION_PATH.with_name(CALIBRATION_PATH.name + ".bak"))
        calib.save(CALIBRATION_PATH)
        res["calibration"] = {"method": how, "distance_cm": cm, "frames": len(iris),
                              "focal_px": round(calib.focal_px, 1), "ear_baseline": round(calib.ear_baseline, 4),
                              "previous_focal_px": round(old.focal_px, 1) if old else None,
                              "saved_to": "FARPOINT_RUNTIME/calibration.local.json (previous kept as .bak)"}
        print(f"Calibration saved (focal {calib.focal_px:.0f} px, eye-opening baseline {calib.ear_baseline:.3f}).")

        # 4. lean test: does the distance follow you?
        print("\nNext: lean in slowly toward the screen, then lean back (8 s).")
        dists: list[float] = []

        def keep_dist(r):
            if r and r.distance_cm:
                dists.append(r.distance_cm)

        run_for(2, lambda r, left: ["GET READY: LEAN IN SLOWLY, THEN LEAN BACK"], lambda r, left: str(int(left) + 1),
                calib)
        beep(1)
        run_for(8, lambda r, left: ["LEAN IN SLOWLY... THEN LEAN BACK", f"{left:.0f} s left"],
                lambda r, left: f"{r.distance_cm:.0f} cm" if (r and r.distance_cm) else "no face", calib, keep_dist)
        beep(2)

        # 5. head turn: does looking away register?
        def angles(store):
            def f_(r):
                if r and r.yaw_deg is not None:
                    store.append((r.yaw_deg, r.pitch_deg))
            return f_

        at_screen, away = [], []
        run_for(3, lambda r, left: ["LOOK AT THE SCREEN"], lambda r, left: str(int(left) + 1), calib, angles(at_screen))
        print("Now turn your head to look at a wall or window beside you (3 s), until the double beep.")
        beep(1)
        run_for(3.5, lambda r, left: ["TURN YOUR HEAD: LOOK AT A WALL OR WINDOW BESIDE YOU"],
                lambda r, left: str(int(left) + 1), calib, angles(away))
        beep(2)

        def looking(a):
            return abs(a[0]) < LOOK_YAW_DEG and abs(a[1]) < LOOK_PITCH_DEG

        screen_frac = sum(looking(a) for a in at_screen) / max(1, len(at_screen))
        away_frac = sum(not looking(a) for a in away) / max(1, len(away))
        rng = (min(dists), max(dists)) if dists else (None, None)
        res["lean_test"] = {"samples": len(dists), "min_cm": round(rng[0], 1) if dists else None,
                            "max_cm": round(rng[1], 1) if dists else None,
                            "range_cm": round(rng[1] - rng[0], 1) if dists else None}
        res["head_turn"] = {"looking_at_screen_rate_when_facing": round(screen_frac, 2),
                            "looking_away_rate_when_turned": round(away_frac, 2),
                            "yaw_deg_facing_median": round(statistics.median(a[0] for a in at_screen), 1) if at_screen else None,
                            "yaw_deg_turned_median": round(statistics.median(a[0] for a in away), 1) if away else None,
                            "thresholds_deg": {"yaw": LOOK_YAW_DEG, "pitch": LOOK_PITCH_DEG}}
        res["checks"] = {"face_found": True,
                         "distance_follows_you": bool(dists and rng[1] - rng[0] >= 10),
                         "facing_counts_as_looking": screen_frac >= 0.8,
                         "head_turn_counts_as_away": away_frac >= 0.6}
        res["status"] = "passed" if all(res["checks"].values()) else "partial"
        summary = (f"Calibrated at {cm:g} cm. Lean test {res['lean_test']['min_cm']}-{res['lean_test']['max_cm']} cm. "
                   f"Facing {screen_frac:.0%} looking, turned {away_frac:.0%} away.")
        print(summary)
        run_for(3, lambda r, left: ["PART A DONE", summary[:70], "next: part B in the console window"])
        return res
    finally:
        cap.release()
        sensor.close()
        pv.close()


# ---- B: live lean-in trial in Edge ----------------------------------------------------------

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Far Point reading test</title>
<style>
body{font-family:'Segoe UI',Arial,sans-serif;margin:0;background:#f6f5ef;color:#222}
#bar{position:sticky;top:0;background:#0b1d2a;color:#fff;padding:18px 28px;box-shadow:0 2px 8px #0004}
#instr{font-size:30px;font-weight:600;line-height:1.25}
#meta{font-size:19px;opacity:.9;margin-top:8px}
main{max-width:760px;margin:26px auto;padding:0 24px;font-size:16px;line-height:1.6}
</style></head><body>
<div id="bar"><div id="instr">Loading...</div><div id="meta"></div></div>
<main>
<h2>A short reading test</h2>
<p>This page is served by Far Point on your own laptop (127.0.0.1). It holds no images and sends nothing anywhere.
The bar above tells you what to do, step by step. Far Point watches your viewing distance through the webcam,
on the laptop only, and decides with a small local model whether larger text would help.</p>
<p>Most people drift closer to the screen when text is small or the work is hard. Holding the eyes close for long
periods asks the focusing muscles to work harder. The usual advice is simple: keep the screen at a comfortable
distance, make the text bigger instead of leaning in, and every so often look at something far away.</p>
<p>When you lean in for more than a few seconds, Far Point enlarges the text by one step so you can sit back.
About thirty seconds later it checks, again through the camera, whether you actually leaned back. That check is
what lets it learn which changes help you and which ones it should stop making.</p>
<p>Everything Far Point changes can be undone, and it undoes it when it stops: the zoom on this page goes back to
where it started when the test ends.</p>
<p>Keep reading this text normally while you follow the instructions in the bar. There is nothing else to do.</p>
</main>
<script>
async function tick(){
  try{const r=await fetch('/state',{cache:'no-store'});const s=await r.json();
    document.getElementById('instr').textContent=s.text;document.getElementById('meta').textContent=s.meta||'';}catch(e){}
  try{await fetch('/beacon',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dpr:window.devicePixelRatio,iw:innerWidth,ow:outerWidth})});}catch(e){}
}
setInterval(tick,400);tick();
</script></body></html>"""


class TrialServer:
    """Serves the reading page, the current instruction (/state) and receives zoom beacons.
    Bound to 127.0.0.1 on a random port, no auth, stops when part B ends."""

    def __init__(self):
        self.state = {"text": "Get ready...", "meta": ""}
        self.beacons: list[tuple[float, float]] = []
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", ctype="text/plain"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/state"):
                    self._send(200, json.dumps(srv.state).encode(), "application/json")
                elif self.path in ("/", "/index.html"):
                    self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                else:
                    self._send(404)

            def do_POST(self):
                if self.path == "/beacon":
                    n = int(self.headers.get("Content-Length") or 0)
                    try:
                        data = json.loads(self.rfile.read(n) or b"{}")
                        srv.beacons.append((time.time(), float(data.get("dpr") or 0)))
                    except ValueError:
                        pass
                self._send(204)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def dpr(self, since: float = 0.0) -> float | None:
        vals = [d for t, d in self.beacons if t >= since]
        return vals[-1] if vals else None

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def edge_path() -> str | None:
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as k:
                p = winreg.QueryValue(k, None)
                if p and Path(p).exists():
                    return p
        except OSError:
            pass
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return p
    return None


def find_window(title_part: str) -> int | None:
    import win32gui
    found: list[int] = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and title_part in win32gui.GetWindowText(h):
            found.append(h)
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def part_b(args) -> dict:
    from farpoint.act import RegistryTheme, WinWindow, WmiBrightness
    from farpoint.config import Settings
    from farpoint.doctrine import DoctrineStore, default_doctrine
    from farpoint.runtime import Runtime

    res: dict = {"part": "b", "date": now_iso(), "status": "failed", "app": "Microsoft Edge (Far Point test page)"}
    if not decider_ctl.health():
        print("The local Decider is not answering. Starting it in text mode (about 1-2 min)...")
        res["decider_start"] = decider_ctl.restart(vision=False)
    info = decider_ctl.health() or {}
    res["decider"] = {"up": bool(info), "vision_server": info.get("vision")}
    exe = edge_path()
    if exe is None:
        res["error"] = "Microsoft Edge not found"
        print("Microsoft Edge was not found; part B needs it.")
        return res

    scratch = SESSION_DIR / "trial"
    shutil.rmtree(scratch, ignore_errors=True)
    store = DoctrineStore(scratch / "profile")
    d0 = default_doctrine()
    store.approve(store.save_draft("lean-in trial: enlarge_text only", d0.profile, d0.limits, [d0.rule(1)]).version)
    theme0, bright0 = RegistryTheme().get(), WmiBrightness().get()
    srv = TrialServer()
    rt = Runtime(Settings(mode="live", runtime_dir=scratch, no_bedrock=True, vision=False, period_s=2.0))
    events: list[dict] = []
    rt.bus.add_listener(events.append)
    dists: list[float] = []
    stop_feed = threading.Event()
    win = WinWindow()
    hwnd = None

    def feeder():
        while not stop_feed.wait(0.25):
            tr = rt.tracker
            d = tr.distance_cm if tr.face else None
            if d is not None:
                dists.append(d)
            near = f", closer than 30 cm for {tr.under_near_s:.0f} s" if (d and d < 30) else ""
            zoom = rt.actuators.zoom.zoom_step()
            srv.state["meta"] = (f"Distance now: {d:.0f} cm{near}." if d else "Distance now: no face seen.") + \
                                f"   Far Point zoom: {zoom:+d}."

    def wait_for(pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            hit = pred()
            if hit:
                return hit
            time.sleep(0.2)
        return None

    try:
        rt.start()
        threading.Thread(target=feeder, daemon=True).start()
        srv.state["text"] = "Get ready: read this page at your normal distance."
        subprocess.Popen([exe, "--new-window", srv.url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        print("An Edge window opened with the instructions at the top. Follow them there.")
        t_open = time.time()
        if wait_for(lambda: srv.dpr(t_open), 20) is None:
            res["error"] = "the Edge page did not load within 20 s"
            print(res["error"])
            return res
        hwnd = wait_for(lambda: find_window("Far Point reading test"), 10)
        if hwnd:
            win.set_foreground(hwnd)
        time.sleep(1.0)
        dpr0 = srv.dpr()
        res["zoom"] = {"dpr_before": dpr0}

        for s in range(5, 0, -1):
            srv.state["text"] = f"Read this at your normal distance... ({s})"
            time.sleep(1)
        d_start = statistics.median(dists[-8:]) if dists else None
        beep(1)
        srv.state["text"] = "Now LEAN IN CLOSE: bring your eyes to about 25 cm from the screen, and hold."
        print("Lean in close (about 25 cm) and hold until the text gets bigger...")
        t_lean = time.time()
        act = wait_for(lambda: next((e["data"] for e in events if e["type"] == "action"
                                     and e["data"]["tool"] == "enlarge_text" and e["data"]["status"] == "done"), None),
                       args.lean_timeout)
        attempts = [e["data"] for e in events if e["type"] == "action"]
        res["actions"] = [{k: a[k] for k in ("tool", "status", "message")} for a in attempts]
        if act is None:
            res["error"] = f"enlarge_text did not fire within {args.lean_timeout:.0f} s"
            srv.state["text"] = "Far Point did not enlarge the text this time. The test will stop now."
            print(res["error"])
        else:
            seconds_to_act = round(time.time() - t_lean, 1)
            dec = next((e["data"] for e in events if e["type"] == "decision" and e["data"]["id"] == act["decision_id"]),
                       {})
            time.sleep(1.0)
            res["zoom"]["dpr_after_action"] = srv.dpr()
            beep(2)
            srv.state["text"] = ("The text just got bigger. Now LEAN BACK to your normal distance (45 cm or more) "
                                 "and keep reading for about 30 s.")
            print("Text enlarged. Lean back to your normal distance and keep reading (30 s)...")
            ver = wait_for(lambda: next((e["data"] for e in events if e["type"] == "verification"
                                         and e["data"]["action_id"] == act["id"]), None), 45)
            res["action"] = {"id": act["id"], "status": act["status"], "message": act["message"],
                             "seconds_after_leaning_in": seconds_to_act, "rule_ref": dec.get("rule_ref"),
                             "decider_latency_ms": dec.get("latency_ms"), "decider_source": dec.get("source"),
                             "rule_1_p": next((r["p"] for r in dec.get("answers", {}).get("rules", []) if r["n"] == 1),
                                              None)}
            res["verification"] = ({k: ver[k] for k in ("outcome", "before", "after", "window_s")} if ver else None)
        srv.state["text"] = "Done. Far Point is putting the zoom back now..."
        time.sleep(0.5)
    finally:
        stop_feed.set()
        rt.stop()  # restores zoom, brightness and theme
        time.sleep(2.0)
        res.setdefault("zoom", {})["dpr_after_restore"] = srv.dpr()
        srv.state["text"] = "All done. This window closes in a moment."
        time.sleep(1.2)
        if hwnd:
            import win32con
            import win32gui
            try:
                if "Far Point reading test" in win32gui.GetWindowText(hwnd):
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        srv.close()

    z = res.get("zoom", {})
    res["distance_cm"] = {"start": round(d_start, 1) if dists and d_start else None,
                          "min": round(min(dists), 1) if dists else None,
                          "max": round(max(dists), 1) if dists else None, "samples": len(dists)}
    res["restore"] = {"runtime_restored": rt.restored, "journal_after": rt.actuators.journal.entries(),
                      "theme_unchanged": RegistryTheme().get() == theme0,
                      "brightness_unchanged": WmiBrightness().get() == bright0}
    zoom_restored = (z.get("dpr_before") is not None and z.get("dpr_after_restore") is not None
                     and abs(z["dpr_after_restore"] - z["dpr_before"]) < 0.01)
    z["zoom_changed_on_action"] = (z.get("dpr_after_action") is not None and z.get("dpr_before") is not None
                                   and z["dpr_after_action"] > z["dpr_before"] + 0.01)
    z["restored"] = zoom_restored
    ver = res.get("verification")
    res["checks"] = {
        "distance_updates": bool(dists) and (max(dists) - min(dists) >= 10),
        "enlarge_text_fired": bool(res.get("action")),
        "page_zoom_grew": bool(z["zoom_changed_on_action"]),
        "verification_recorded": bool(ver),
        "verification_worked": bool(ver and ver["outcome"] == "worked"),
        "zoom_restored": bool(zoom_restored),
        "theme_and_brightness_unchanged": res["restore"]["theme_unchanged"] and res["restore"]["brightness_unchanged"],
        "journal_empty": res["restore"]["journal_after"] == {},
    }
    must = ("distance_updates", "enlarge_text_fired", "verification_recorded", "zoom_restored",
            "theme_and_brightness_unchanged", "journal_empty")
    res["status"] = "passed" if all(res["checks"][k] for k in must) else "failed"
    print(f"Part B {res['status'].upper()}: " + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in res["checks"].items()))
    return res


# ---- C: S2 labeled capture -----------------------------------------------------------------

class VisionServer:
    """Restarts the Decider with -Vision in the background and warms it up (no camera image)."""

    def __init__(self):
        self.result: dict | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        r = decider_ctl.restart(vision=True)
        if r["ok"]:
            r["warm_up"] = decider_ctl.warm_up_vision()
        self.result = r

    def join(self, timeout: float = 600.0) -> dict:
        self.thread.join(timeout)
        return self.result or {"ok": False, "error": "vision restart still running"}


def part_c(args, state: dict) -> dict:
    from farpoint.doctrine import DoctrineStore

    res: dict = {"part": "c", "date": now_iso(), "status": "failed"}
    print("Starting the local Decider in vision mode in the background (needed for part D)...")
    state["vision_server"] = VisionServer()
    g = ask("Do you wear glasses for screen work?  Y = yes, N = no:", {"y", "n"})
    glasses_for_screen = "yes" if g == "y" else "no"
    src = ask("Do you have a pair of glasses with you right now?  Y = my own, P = another pair as a prop, N = none:",
              {"y", "p", "n"})
    if src == "n":
        print("Please grab any pair of glasses (reading glasses, sunglasses, a spare pair). They are only a prop.")
        src = ask("Press P when you have a pair, or N to skip the capture:", {"p", "n"})
    store = DoctrineStore(RUNTIME / "profile")
    store.update_profile(glasses_for_screen=glasses_for_screen)
    res["glasses_for_screen"] = glasses_for_screen
    res["profile_updated"] = "FARPOINT_RUNTIME/profile/doctrine.json: glasses_for_screen=" + glasses_for_screen
    if src == "n":
        res.update(status="skipped", reason="no glasses available, so glasses_on cannot be labeled")
        return res
    source = "own" if src == "y" else "prop"
    res["glasses_source"] = source
    print("\nThe camera window shows each pose and a countdown. Capture starts at the beep and ends at the double beep.")
    print("Poses: glasses on/off, looking at the screen or far away, rubbing your eyes, leaning in. About 1 minute.")
    if ask("Put your glasses ON, then press ENTER to start the capture (S = skip):", {"enter", "s"}) == "s":
        res["status"] = "skipped"
        return res
    rc = subprocess.call([PY, str(ROOT / "eval" / "spike_s2.py"), "capture", "--preview",
                          "--glasses-source", source, "--glasses-for-screen", glasses_for_screen], cwd=ROOT)
    cap_file = RESULTS / "s2_capture.json"
    if rc == 0 and cap_file.exists():
        cap = json.loads(cap_file.read_text())
        res.update(status="passed" if cap.get("n_frames", 0) >= 40 else "failed", n_frames=cap.get("n_frames"),
                   dark_poses=cap.get("dark_poses"))
    else:
        res["error"] = f"capture exited with {rc}"
    return res


# ---- D: S2 scoring + decision ----------------------------------------------------------------

def part_d(args, state: dict) -> dict:
    res: dict = {"part": "d", "date": now_iso(), "status": "failed"}
    vs = state.get("vision_server")
    print("Waiting for the vision Decider (it started during part C)...")
    res["vision_server"] = vs.join() if vs else decider_ctl.restart(vision=True)
    if vs is None and res["vision_server"]["ok"]:
        res["vision_server"]["warm_up"] = decider_ctl.warm_up_vision()
    if not res["vision_server"].get("ok"):
        res["error"] = "the Decider did not come up in vision mode"
        print(res["error"])
    else:
        print("Scoring the 48 labeled frames on the local vision Decider (about 30-60 s)...")
        rc = subprocess.call([PY, str(ROOT / "eval" / "spike_s2.py"), "score"], cwd=ROOT)
        if rc == 0:
            subprocess.call([PY, str(ROOT / "eval" / "spike_s2.py"), "decide"], cwd=ROOT)
            d = json.loads((RESULTS / "s2_decision.json").read_text())
            res.update(status="passed" if d["pass"] else "failed (below the 85% gate)", decision=d)
            print("\n" + "#" * 60)
            print(f"  S2 {'PASS' if d['pass'] else 'FAIL'}: " + ", ".join(f"{k} {v:.0%}" for k, v in d["accuracy"].items()))
            print("  Vision mode: " + ("ALLOWED (turns on when the Decider runs with -Vision)" if d["pass"]
                                       else "stays OFF (text-only)"))
            print("#" * 60)
            if d["pass"]:
                print("Checking the vision path end to end for 10 s (dry run, nothing changes on screen)...")
                subprocess.call([PY, str(ROOT / "scripts" / "smoke_vision.py"), "--seconds", "10", "--keep-vision",
                                 "--out", str(SESSION_DIR / "vision-smoke.json")], cwd=ROOT)
                vs_path = SESSION_DIR / "vision-smoke.json"
                if vs_path.exists():
                    v = json.loads(vs_path.read_text())
                    res["vision_smoke"] = {"ok": v.get("ok"), **{k: v.get("loop", {}).get(k) for k in (
                        "decisions", "with_vision_answers", "vision_latency_ms_p50", "text_latency_ms_p50")}}
        else:
            res["error"] = f"scoring exited with {rc}"
    frames = RUNTIME / "s2-frames"
    if frames.exists() and any(frames.glob("pose*_*.jpg")):
        if ask("Delete the captured face frames from FARPOINT_RUNTIME\\s2-frames now?  Y = delete, N = keep:",
               {"y", "n"}, default="y") == "y":
            shutil.rmtree(frames, ignore_errors=True)
            res["frames_deleted"] = True
            print("Frames deleted. The aggregate numbers stay in results/.")
        else:
            res["frames_deleted"] = False
    print("Switching the Decider back to text mode in the background (Far Point's default)...")
    state["text_restart"] = decider_ctl.start(vision=False)
    res["decider_after"] = "text (restart started)"
    return res


# ---- E: rulebook approval in the dashboard ---------------------------------------------------

def part_e(args) -> dict:
    res: dict = {"part": "e", "date": now_iso()}
    if not (ROOT / "web" / "dist" / "index.html").exists():
        res.update(status="skipped", reason="web/dist is not built yet; do the approval once the UI lands")
        print("Part E skipped: the dashboard UI (web/dist) is not built yet.")
        return res
    res.update(status="skipped", reason="run the live app and approve the rulebook in the dashboard")
    print("Start Far Point (python -m farpoint.app --mode live) and approve the rulebook at http://127.0.0.1:8765/.")
    return res


# ---- main --------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", default="abcd", help="which parts to run, e.g. abcd or b")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--lean-timeout", type=float, default=45.0)
    args = ap.parse_args(argv)
    parts = [p for p in args.parts.lower() if p in "abcde"]
    print("Far Point guided session. Parts: " + ", ".join(p.upper() for p in parts) + ". About 8-10 minutes in all.")
    print("Every part waits for ENTER. S skips a part, Q quits. Results go to results/*.json.")
    progress("session", "start", parts="".join(parts))
    state: dict = {}
    titles = {"a": ("CAMERA CHECK AND CALIBRATION", "1.5 min"), "b": ("LEAN-IN TRIAL IN EDGE", "1.5-2 min"),
              "c": ("LABELED CAPTURE FOR IMAGE MODE (S2)", "1.5 min"), "d": ("SCORING AND THE VISION DECISION", "1-3 min"),
              "e": ("RULEBOOK APPROVAL IN THE DASHBOARD", "1 min")}
    files = {"a": "human_a_camera.json", "b": "human_b_lean_in.json", "c": "human_c_capture.json",
             "d": "human_d_s2.json", "e": "human_e_approval.json"}
    done: dict[str, str] = {}
    for p in parts:
        header(p, *titles[p])
        while True:
            k = start_gate(p)
            if k == "q":
                print("Quitting. Parts done so far are saved.")
                return 0
            if k == "s":
                save(files[p], {"part": p, "date": now_iso(), "status": "skipped", "reason": "skipped by the user"})
                done[p] = "skipped"
                break
            try:
                fn = {"a": part_a, "b": part_b, "c": lambda a: part_c(a, state), "d": lambda a: part_d(a, state),
                      "e": part_e}[p]
                res = fn(args)
            except KeyboardInterrupt:
                res = {"part": p, "date": now_iso(), "status": "interrupted"}
            except Exception as e:  # noqa: BLE001 - keep the session going
                import traceback
                traceback.print_exc()
                res = {"part": p, "date": now_iso(), "status": "error", "error": f"{type(e).__name__}: {e}"}
            res["session_time"] = elapsed()
            save(files[p], res)
            done[p] = res["status"]
            print(f"Part {p.upper()}: {res['status']}  (saved results/{files[p]})")
            if res["status"] in ("passed", "skipped") or p in ("c", "d", "e"):
                break
            if ask(f"Redo part {p.upper()}?  R = redo, ENTER = go on:", {"r", "enter"}, default="enter") != "r":
                break
    tr = state.get("text_restart")
    if tr is not None:
        print("Waiting for the Decider to finish switching back to text mode...")
        print("  " + json.dumps(decider_ctl.wait(tr, vision=False)))
    progress("session", "end", parts=done)
    print("\n" + "=" * 72)
    print(" SESSION DONE in " + elapsed() + ": " + ", ".join(f"{p.upper()} {s}" for p, s in done.items()))
    print(" Thank you. You can close this window.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
