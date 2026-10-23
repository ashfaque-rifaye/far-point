"""Film the dashboard for the demo video while the real agent replays the demo trace.

Starts the backend in replay mode with the real local Decider and Amazon Nova (dry-run actuators, so
nothing on the desktop changes), drives Edge through the scenes the narration needs, and captures
the page with screenshots at 1920x1080. Writes dashboard.mp4 plus marks.json (seconds from the start
of the recording for each scene). scripts/video_build.py cuts the final video.

--coach-only films just the Nova part (rulebook and report) into dashboard_coach.mp4 / marks_coach.json.

Needs the Decider on 127.0.0.1:8099 (scripts/start_decider.ps1) and port 8765 free.

    uv run --no-project --with playwright python scripts/video_record_scenes.py [--coach-only]
"""
import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("MYRMIDON_RUNTIME", r"E:\myrmidon-runtime"))
OUT = RUNTIME / "recordings" / "video"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
BASE = "http://127.0.0.1:8765/"
VIEW = {"width": 1600, "height": 900}  # x1.2 device scale = 1920x1080 frames
EYES = "I'm minus 3.5 in both eyes and I take my glasses off to read in the evening. Glare bothers me at night."


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def assemble(index: list[tuple[float, str]], end: float, frames: Path, dst_name: str) -> Path:
    """Variable-rate screenshots -> constant 30 fps H.264."""
    lines = []
    for i, (t, name) in enumerate(index):
        nxt = index[i + 1][0] if i + 1 < len(index) else end
        t = 0.0 if i == 0 else t  # the first frame holds from the start of the recording
        lines += [f"file '{frames.name}/{name}'", f"duration {max(nxt - t, 0.001):.4f}"]
    lines.append(f"file '{frames.name}/{index[-1][1]}'")
    (OUT / "frames.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    dst = OUT / dst_name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", "frames.txt", "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
                    "-c:v", "libx264", "-crf", "16", "-preset", "medium", str(dst)], cwd=OUT, check=True)
    return dst


async def replay_scenes(mark, at_trace, go, page) -> None:
    """Screens timed to the demo trace (segments in scripts/make_demo_trace.py)."""
    await at_trace(48)
    await go("reflex")
    mark("reflex")
    await page.wait_for_timeout(1500)
    item = page.locator(".feed-item.act").last
    if await item.count():
        await item.click()
        mark("reflex_open")
    await at_trace(60)
    await go("now")
    mark("now_dark")
    await at_trace(132)
    await go("reflex")
    mark("reflex_deny")
    await at_trace(150)
    await go("now")
    mark("now_break")
    await at_trace(205)
    await go("day")
    mark("day")
    await at_trace(243)


async def adopt_latest(page, settle_ms: int = 3000) -> None:
    """Click "Adopt vN" once the draft stops changing (Nova can write two drafts in one turn)."""
    adopt = page.get_by_role("button", name="Adopt v")
    approve = page.locator(".modal .btn.grad")
    for _ in range(4):
        if await approve.count():
            # Nova called adopt_doctrine itself: the ConfirmGate intervention asks the user first
            await page.wait_for_timeout(2500)
            await approve.click()
            await page.wait_for_timeout(1500)
            if not await adopt.count():
                return
        if not await adopt.count():
            await page.wait_for_timeout(500)
            continue
        label = await adopt.inner_text()
        await page.wait_for_timeout(settle_ms)
        if not await adopt.count() or await adopt.inner_text() != label:
            continue
        await adopt.click()  # the click is the approval: a single-use token passes the ConfirmGate
        try:
            await adopt.wait_for(state="detached", timeout=10000)
            return
        except Exception:  # noqa: BLE001  (a newer draft arrived; adopt that one)
            continue
    raise RuntimeError("the rulebook draft never settled")


async def coach_scenes(mark, go, page) -> None:
    """Amazon Nova: a rulebook from the user's words, adopted with one click, then a report."""
    await go("rules")
    mark("rules")
    await page.wait_for_timeout(1200)
    await page.locator("#eyes").fill(EYES)
    await page.wait_for_timeout(1500)
    await page.get_by_role("button", name="Draft my rulebook").click()
    mark("rules_draft")
    adopt = page.get_by_role("button", name="Adopt v")
    await page.locator(".modal .btn.grad, button:has-text('Adopt v')").first.wait_for(timeout=120000)  # Nova's draft
    mark("rules_drafted")
    await adopt_latest(page, settle_ms=2500)
    mark("rules_adopted")
    await page.wait_for_timeout(4000)

    await go("report")
    mark("report")
    await page.wait_for_timeout(1200)
    await page.get_by_role("button", name="Today").first.click()
    mark("report_ask")
    await page.locator(".md").first.wait_for(timeout=90000)
    mark("report_ready")
    await page.wait_for_timeout(6000)
    await page.mouse.wheel(0, 500)
    await page.wait_for_timeout(4000)
    mark("end")


async def main(coach_only: bool) -> None:
    from playwright.async_api import async_playwright

    if port_open(8765):
        sys.exit("port 8765 is busy: stop the other Myrmidon backend first")
    if not port_open(8099):
        sys.exit("the Decider is not listening on 8099: run scripts/start_decider.ps1")
    suffix = "_coach" if coach_only else ""
    frames = OUT / f"frames{suffix}"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)

    # Replay mode keeps its own profile; start from the default rulebook every take, or the rulebook
    # adopted in the last take changes the story's timing (a lower break limit fires a break early).
    shutil.rmtree(RUNTIME / "replay" / "profile", ignore_errors=True)
    log = open(OUT / f"backend{suffix}.log", "w", encoding="utf-8")
    backend = None
    try:
        async with async_playwright() as p:
            # Open Edge before the replay starts: on a busy machine its launch alone can take 20 s.
            browser = await p.chromium.launch(channel="msedge")
            ctx = await browser.new_context(viewport=VIEW, device_scale_factor=1.2)
            page = await ctx.new_page()
            backend = subprocess.Popen(
                [str(PY), "-m", "myrmidon.app", "--mode", "replay",
                 "--trace", str(ROOT / "myrmidon/replay/demo_session.jsonl"), "--dry-run",
                 # coach-only: crawl through the calm opening so no break screen covers the page
                 "--speed", "0.05" if coach_only else "1"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            while not port_open(8765):
                if backend.poll() is not None:
                    sys.exit("backend exited, see " + log.name)
                await asyncio.sleep(0.05)
            trace0 = time.time()  # the replay starts with the server

            index: list[tuple[float, str]] = []
            writer = ThreadPoolExecutor(1)  # keep disk writes off the event loop that drives the page
            filming = True

            async def film() -> None:
                # A screenshot loop rather than the DevTools screencast, which stalled on this machine.
                while filming:
                    t = time.time()
                    try:
                        jpg = await page.screenshot(type="jpeg", quality=90)
                    except Exception:  # noqa: BLE001  (navigation in progress)
                        await asyncio.sleep(0.05)
                        continue
                    name = f"{len(index):06d}.jpg"
                    index.append((t, name))
                    writer.submit((frames / name).write_bytes, jpg)
                    await asyncio.sleep(max(0.0, 0.1 - (time.time() - t)))

            await page.goto(f"{BASE}?theme=day" + ("#rules" if coach_only else ""))
            stale = page.get_by_role("button", name="Adopt v")  # a draft left waiting by an earlier run
            await page.wait_for_timeout(1500)
            if await stale.count():
                await adopt_latest(page, settle_ms=500)
            camera = asyncio.ensure_future(film())
            video0 = time.time()
            marks: dict[str, float] = {"trace_offset": round(trace0 - video0, 2)}

            def mark(name: str) -> None:
                marks[name] = round(time.time() - video0, 2)
                print(f"{marks[name]:7.2f}  {name}", flush=True)

            async def at_trace(t: float) -> None:
                await asyncio.sleep(max(0.0, trace0 + t - time.time()))

            async def go(screen: str) -> None:
                await page.evaluate(f"location.hash = '{screen}'")

            mark("now")
            if not coach_only:
                await replay_scenes(mark, at_trace, go, page)
            await coach_scenes(mark, go, page)
            end = time.time()

            filming = False
            await camera
            writer.shutdown(wait=True)
            await ctx.close()
            await browser.close()
        index = [(t - video0, n) for t, n in index]
        (OUT / f"marks{suffix}.json").write_text(json.dumps(marks, indent=1))
        print("frames", len(index), "saved", assemble(index, end - video0, frames, f"dashboard{suffix}.mp4"))
    finally:
        if backend is not None:
            backend.terminate()
            try:
                backend.wait(10)
            except subprocess.TimeoutExpired:
                backend.kill()
        log.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coach-only", action="store_true", help="film only the rulebook and report scenes")
    asyncio.run(main(ap.parse_args().coach_only))
