"""End-to-end check of the running backend as the UI sees it.

  python scripts/e2e_ui_check.py            # backend in replay mode, FAKE Decider, Bedrock off
  python scripts/e2e_ui_check.py --live     # backend in live mode (real Decider, camera, Bedrock if creds)

1. Starts `python -m farpoint.app` on 127.0.0.1:8765 in its own process group.
2. GET / and every /assets/* that index.html references: all must be 200, and no file may load
   from an http(s) origin other than 127.0.0.1/localhost (no CDNs). If web/dist is not built,
   it records that and checks the WebSocket only.
3. Opens /ws, validates every frame for `--seconds` against web/contract.schema.json, sends each
   of the 10 commands with valid args, and checks the documented reply type.
4. Stops the backend with Ctrl+Break (uvicorn runs the shutdown) and checks the log says
   "restored on exit".
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farpoint.contract import errors  # noqa: E402

BASE = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765/ws"
LOCAL_ORIGIN = re.compile(r"https?://(127\.0\.0\.1|localhost)(:\d+)?(/|$)")


def http_get(path: str, timeout: float = 5.0) -> tuple[int, bytes, str]:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, r.read(), r.headers.get("content-type", "")


def wait_up(timeout: float = 90.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            http_get("/", timeout=2)
            return True
        except OSError:
            time.sleep(0.5)
    return False


def check_static(report: dict) -> bool:
    dist = Path(os.environ.get("FARPOINT_WEB_DIST", ROOT / "web" / "dist"))
    status, body, ctype = http_get("/")
    if not (dist / "index.html").exists():
        report["ui"] = f"UI dist not available at {datetime.now():%Y-%m-%d %H:%M} ({dist}); WebSocket checked only"
        report["root"] = {"status": status, "body": body.decode()[:80]}
        return status == 200
    html = body.decode("utf-8", "replace")
    refs = sorted(set(re.findall(r'(?:src|href)="([^"]+)"', html)))
    assets = [r for r in refs if r.startswith("/assets/") or r.startswith("./assets/") or r.startswith("assets/")]
    external = [r for r in refs if r.startswith(("http://", "https://", "//")) and not LOCAL_ORIGIN.match(r)]
    results, ok = {}, status == 200 and "html" in ctype
    for a in assets:
        p = "/" + a.lstrip("./")
        try:
            st, data, _ = http_get(p)
        except OSError as e:
            st, data = getattr(e, "code", 0), b""
        results[p] = st
        ok &= st == 200
        if p.endswith((".js", ".css")):
            text = data.decode("utf-8", "replace")
            for m in re.findall(r"""https?://[^\s"'`)]+""", text):
                if not LOCAL_ORIGIN.match(m) and not m.startswith(("http://www.w3.org", "https://www.w3.org")):
                    external.append(f"{p}: {m[:80]}")
    report["ui"] = {"index": status, "assets": results, "external_origins": external[:20]}
    return ok and not external


COMMANDS = [
    ("set_eye_description", {"text": "Myopia -3.5 both eyes, glasses for screen work, glare bothers me at night."},
     {"doctrine", "toast"}),
    ("approve_doctrine", {"version": None}, {"doctrine", "toast"}),
    ("approve_proposal", {"id": "p_999999"}, {"proposal", "toast"}),
    ("reject_proposal", {"id": "p_999999"}, {"proposal", "toast"}),
    ("start_calibration", {"distance_cm": 50}, {"toast"}),
    ("request_report", {"period": "today"}, {"report", "toast"}),
    ("draft_exam_email", {}, {"email_draft", "toast"}),
    ("confirm", {"request_id": "c_999999", "approve": False}, {"toast", "email_draft"}),
    ("pause_camera", {"paused": True}, {"hello"}),
    ("skip_break", {"id": "b_999999"}, {"break", "toast"}),
]


async def check_ws(seconds: float, report: dict, live: bool) -> bool:
    import websockets
    frames, bad = [], []
    ok = True
    async with websockets.connect(WS, origin=BASE, max_size=2 ** 22) as ws:
        end = time.time() + seconds
        while time.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.time()))
            except asyncio.TimeoutError:
                break
            m = json.loads(raw)
            frames.append(m)
            e = errors(m, "ServerEvent")
            if e:
                bad.append({"type": m.get("type"), "errors": e[:3]})
        doctrine = next((f for f in reversed(frames) if f["type"] == "doctrine"), None)
        types = {}
        for f in frames:
            types[f["type"]] = types.get(f["type"], 0) + 1
        report["frames"] = {"count": len(frames), "by_type": types, "schema_errors": bad[:10]}
        ok &= not bad and frames[:1] and frames[0]["type"] == "hello"
        replies = {}
        for name, args, expect in COMMANDS:
            if name == "approve_doctrine":
                args = {"version": doctrine["data"]["version"] if doctrine else 1}
            if name == "start_calibration" and live:
                # Live calibration would overwrite the real baseline with a guessed distance.
                replies[name] = {"reply": "skipped", "detail": "live: needs a person at a measured distance"}
                continue
            await ws.send(json.dumps({"v": 1, "type": "cmd", "name": name, "args": args, "t": int(time.time() * 1000)}))
            got = None
            deadline = time.time() + (60 if name in ("set_eye_description", "request_report", "draft_exam_email",
                                                     "start_calibration") else 10)
            while time.time() < deadline:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time())))
                except asyncio.TimeoutError:
                    break
                if errors(m, "ServerEvent"):
                    bad.append({"type": m.get("type"), "after": name})
                if m["type"] in expect and m["type"] not in ("signals", "decision", "stats"):
                    if m["type"] == "hello" and m["data"]["camera"]["status"] != "paused":
                        continue
                    got = m
                    break
            replies[name] = {"reply": got["type"] if got else None,
                             "detail": (got["data"].get("text") or got["data"].get("status") or
                                        got["data"].get("camera") or got["data"].get("version")) if got else None}
            ok &= got is not None
        await ws.send(json.dumps({"v": 1, "type": "cmd", "name": "pause_camera", "args": {"paused": False}}))
        await asyncio.sleep(0.5)
        report["commands"] = replies
    return bool(ok) and not bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--actuate", action="store_true", help="live: let the loop change zoom/brightness/theme")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    runtime = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))
    log_path = runtime / "logs" / f"e2e-ui-check-{datetime.now():%Y%m%d-%H%M%S}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, "-m", "farpoint.app"]
    if a.live:
        args += ["--mode", "live"] + ([] if a.actuate else ["--dry-run"])
    else:
        args += ["--mode", "replay", "--fake-decider", "--no-bedrock", "--loop-replay"]
    mode = ("live (real camera, Decider, Bedrock if creds; " + ("REAL actuators)" if a.actuate else "dry-run actuators)")
            if a.live else "replay (FAKE Decider, Bedrock off, dry-run)")
    report: dict = {"mode": mode, "log": str(log_path)}
    # The backend under test gets its own runtime dir, so the check never leaves drafts, stats or
    # moments in the real profile. It still reads the real calibration and face model.
    env = dict(os.environ)
    env["FARPOINT_RUNTIME"] = str(runtime / "e2e-check")
    env.setdefault("FARPOINT_CALIBRATION", str(runtime / "calibration.local.json"))
    env.setdefault("FARPOINT_FACE_MODEL", str(runtime / "models" / "face_landmarker.task"))
    report["runtime"] = env["FARPOINT_RUNTIME"]
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        ok = False
        try:
            if not wait_up():
                report["error"] = "backend did not come up"
            else:
                ok_static = check_static(report)
                ok_ws = asyncio.run(check_ws(a.seconds, report, a.live))
                ok = ok_static and ok_ws
        finally:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.kill()
                report["shutdown"] = "killed after 30 s"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    restored = [ln for ln in text.splitlines() if "restored on exit" in ln]
    report["restored_log"] = restored[-1][-160:] if restored else None
    ok = ok and bool(restored)
    report["ok"] = bool(ok)
    out = json.dumps(report, indent=2)
    print(out)
    if a.out:
        a.out.write_text(out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
