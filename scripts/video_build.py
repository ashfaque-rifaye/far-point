"""Cut the demo video (docs: VIDEO_SCRIPT.md) from the dashboard recording, the doc images and a narration.

Inputs: <runtime>/recordings/video/dashboard.mp4 and marks.json from scripts/video_record_scenes.py,
docs/images/*.png. Narration is spoken locally by Kokoro (scripts/video_tts.py, its own environment).
Output: <runtime>/recordings/video/far-point-demo.mp4 (1920x1080, 30 fps) and far-point-demo.srt.

    uv run --no-project --with playwright python scripts/video_build.py
"""
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "images"
RUNTIME = Path(os.environ.get("FARPOINT_RUNTIME", r"E:\farpoint-runtime"))
OUT = RUNTIME / "recordings" / "video"
WORK = OUT / "build"
TTS_PY = RUNTIME / "tts-env" / "Scripts" / "python.exe"
FPS = 30
LEAD_S = 0.35  # silence before each scene's narration
TAIL_S = 0.55  # and after it
REPLAY_BADGE = ("Replay of a synthetic trace through the real agent: Strands Decider 2B on the laptop GPU, "
                "Amazon Nova on Bedrock. Desktop changes are dry-run.")

# Clip windows: ("v", start, end) seconds in dashboard.mp4, ("m", mark, mark) marks in it (a mark may
# carry "+seconds"), ("c", mark, mark) marks in dashboard_coach.mp4. The window is fitted to the
# narration: sped up (and labelled) when longer, slowed when shorter (only used on still screens).
# The windows below were picked by looking at the recorded frames.
SCENES = [
    dict(id="hook", image="cover.png", bg="#070d18", lines=[
        "It's late. The glasses are off, the page is small, and you've crept to twenty-seven centimetres "
        "from the screen without noticing.",
        "Far Point is a laptop agent that notices for you, and changes the screen so you can sit back."]),
    dict(id="arch", image="architecture.png", bg="#eef1f7", lines=[
        "Everything on the left runs on the laptop.",
        "The webcam measures viewing distance, eye opening and blinks, and every frame is dropped after measuring.",
        "Every two and a half seconds, Strands Decider 2B, running locally on the GPU, picks which tool to use.",
        "Amazon Nova on Bedrock only ever gets words and numbers."]),
    dict(id="close", clip=("v", 0.0, 14.0), lines=[
        "This is the real agent, replaying a recorded session.",
        "The readings come from a trace, but every decision is live: the real Decider, the real gates, the real Nova.",
        "Distance drops to twenty-seven centimetres, and the eyes narrow."]),
    dict(id="decide", clip=("v", 14.0, 16.4), lines=[
        "The Decider answers one yes-or-no question per rule, all in one request, in about half a second.",
        "Rule one, enlarge text, comes back yes.",
        "Code applies the priority order, and a Strands agent runs the tool."]),
    dict(id="verify", clip=("v", 16.4, 44.2), lines=[
        "Thirty seconds later, the camera checks whether it helped."]),
    dict(id="worked", clip=("v", 44.2, 46.9), lines=[
        "Twenty-seven to forty-five centimetres. It worked."]),
    dict(id="reflex", clip=("m", "reflex", "now_dark"), lines=[
        "Every decision is logged with exactly what the Decider read.",
        "Code turns each number into a verdict, so the model only has to judge words.",
        "One nine-way question scored sixty-eight percent. One question per rule scored eighty-seven and a half."]),
    dict(id="deny", clip=("v", 98.0, 136.0), lines=[
        "Now a far-look break is due, but the user is on a Teams call.",
        "A Strands intervention, the Interrupt Gate, reuses the Decider's interrupt answer, and holds the break."]),
    dict(id="break", clip=("v", 157.0, 199.0), lines=[
        "After the call, the break runs.",
        "It only counts when the camera sees the user look away for twenty seconds."]),
    dict(id="rules", clip=("c", "rules", "rules_adopted+2.5"), lines=[
        "Amazon Nova writes the rulebook from the user's own words.",
        "Nothing changes until they approve it."]),
    dict(id="report", clip=("c", "report_ask", "end"), lines=[
        "Nova also writes a numbers-only report to bring to an eye exam. It never sees an image."]),
    dict(id="results", image="decision-loop.png", bg="#eef1f7", lines=[
        "On seventy-two preregistered test states, Nova Lite alone was just as accurate, "
        "but it took two and a half seconds and eleven times the tokens.",
        "The hybrid also scored one hundred percent, and asked Nova only when a rule was unsure."]),
    dict(id="pattern", card="pattern", lines=[
        "The decision pattern, Reflex Gate, is reusable and open source, with its Strands interventions.",
        "Far Point. Not a medical device. Just a kinder screen."]),
    dict(id="end", card="end", hold=4.0, lines=[]),
]

PATTERN_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{font-family:'Segoe UI',Arial,sans-serif;color:#e9effa;background:radial-gradient(900px 600px at 90% -10%,rgba(59,108,246,.35),transparent 60%),radial-gradient(800px 500px at -5% 110%,rgba(47,211,196,.28),transparent 60%),#070d18}
.k{font-size:22px;font-weight:800;letter-spacing:3px;color:#36dccd}
h1{font-size:64px;margin:14px 0 8px;letter-spacing:-1.5px}
.p{font-family:Consolas,monospace;font-size:28px;color:#9fb0cc}
.wrap{position:absolute;left:110px;top:100px;right:110px}
.grid{display:grid;grid-template-columns:1.05fr 1fr;gap:48px;margin-top:46px}
pre{margin:0;background:#0d1b2a;border:1px solid #22324a;border-radius:24px;padding:30px 34px;font:22px/1.5 Consolas,monospace;color:#d6e2f5;white-space:pre-wrap}
.s{color:#7ee2b8}.c{color:#6f84a6}
ul{margin:0;padding:0;list-style:none}
li{font-size:29px;line-height:1.35;margin:0 0 24px;padding-left:40px;position:relative;color:#d6e2f5}
li:before{content:'';position:absolute;left:0;top:14px;width:16px;height:16px;border-radius:50%;background:linear-gradient(120deg,#2fd3c4,#3b6cf6)}
b{color:#fff}
</style></head><body><div class="wrap">
<div class="k">REUSABLE DECISION PATTERN · #tool-selection</div>
<h1>Reflex Gate</h1><div class="p">patterns/reflex_gate/ · Apache-2.0</div>
<div class="grid"><pre><span class="c"># one typed question per rule</span>
{"type": "noul",
 "instructions": "Does rule 1 apply right now?",
 "criteria": {
   "true":  "the line says <span class="s">'enlarging needed'</span>",
   "false": "the line says <span class="s">'no enlarging needed'</span>"}}

resp = decider.ask(state_text, build_questions(rules))
sel  = select(rules, resp["answers"], escalate=nova)
gate.prime(sel.interrupt_p)
getattr(agent.tool, sel.tool)()  <span class="c"># interventions run</span></pre>
<ul>
<li><b>One noul per rule</b> plus <b>interrupt_ok</b>, all in one Decider request</li>
<li><b>Code applies the priority order</b>: fire at p ≥ 0.65, clear at p ≤ 0.35</li>
<li><b>Unsure</b> → ask an LLM on the same text, else stay quiet</li>
<li><b>InterruptGate</b> and <b>ConfirmGate</b> are Strands InterventionHandlers</li>
<li>Fakes for tests, and a posture-coach example</li>
</ul></div></div></body></html>"""

END_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{font-family:'Segoe UI',Arial,sans-serif;color:#e9effa;background:radial-gradient(900px 600px at 85% -10%,rgba(59,108,246,.35),transparent 60%),radial-gradient(800px 500px at -5% 110%,rgba(47,211,196,.30),transparent 60%),#070d18;display:flex;align-items:center;justify-content:center;text-align:center}
.brand{font-size:92px;font-weight:700;letter-spacing:-3px;display:flex;align-items:center;gap:28px;justify-content:center}
.u{font-family:Consolas,monospace;font-size:36px;color:#b6c3d9;margin-top:30px}
.chips{display:flex;gap:16px;justify-content:center;margin-top:40px}
.chip{padding:12px 24px;border-radius:999px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);font-size:28px;font-weight:600}
.g{background:linear-gradient(120deg,#2fd3c4,#3b6cf6);color:#04101c;border:0}
.f{font-size:23px;color:#7f8ea8;margin-top:64px;line-height:1.6}
</style></head><body><div>
<div class="brand"><svg width="96" height="96" viewBox="0 0 64 64"><defs><linearGradient id="l" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2fd3c4"/><stop offset="1" stop-color="#3b6cf6"/></linearGradient></defs><rect width="64" height="64" rx="20" fill="#e9effa"/><circle cx="32" cy="32" r="16" fill="none" stroke="url(#l)" stroke-width="5"/><circle cx="32" cy="32" r="6" fill="url(#l)"/></svg>Far Point</div>
<div class="u">github.com/ashfaque-rifaye/far-point</div>
<div class="chips"><span class="chip g">#strands-decider-2b</span><span class="chip">#tool-selection</span></div>
<div class="f">Strands Decider 2B · Strands Agents · Amazon Bedrock (Nova Lite)<br>
Not a medical device. Narration spoken by Kokoro TTS on the laptop.<br>
Dashboard footage: a synthetic trace replayed through the real agent.</div>
</div></body></html>"""

FRAME_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:%s}
img{width:1920px;height:1080px;object-fit:contain;display:block}</style></head>
<body><img src="%s"></body></html>"""

BADGE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;background:transparent}
span{display:inline-block;font:600 19px 'Segoe UI',Arial,sans-serif;color:#fff;background:rgba(7,13,24,.82);
border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:9px 18px;white-space:nowrap}
b{color:#36dccd}</style></head><body><span>%s</span></body></html>"""


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def probe_len(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def speak() -> dict:
    spec = [{"id": s["id"], "lines": s["lines"]} for s in SCENES if s["lines"]]
    blob = json.dumps(spec, sort_keys=True).encode()
    tts = WORK / "tts"
    stamp = tts / "spec.sha"
    if not (stamp.exists() and stamp.read_text() == hashlib.sha256(blob).hexdigest()):
        tts.mkdir(parents=True, exist_ok=True)
        (tts / "narration.json").write_bytes(blob)
        env = dict(os.environ, HF_HOME=str(RUNTIME / "hf"))
        subprocess.run([str(TTS_PY), str(ROOT / "scripts" / "video_tts.py"), str(tts / "narration.json"), str(tts)],
                       check=True, env=env)
        stamp.write_text(hashlib.sha256(blob).hexdigest())
    return json.loads((tts / "timings.json").read_text(encoding="utf-8"))


async def render_stills() -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge")
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        for s in SCENES:
            if "image" in s:
                html = FRAME_HTML % (s["bg"], (IMG / s["image"]).as_uri())
                (WORK / f"{s['id']}.html").write_text(html, encoding="utf-8")
                await page.goto((WORK / f"{s['id']}.html").as_uri())
            elif "card" in s:
                await page.set_content(PATTERN_HTML if s["card"] == "pattern" else END_HTML)
            else:
                continue
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(WORK / f"{s['id']}.png"))
        badge = await browser.new_page(viewport={"width": 1900, "height": 80})
        for name, text in [("replay", REPLAY_BADGE)] + [(f"x{n}", f"<b>{n}× speed</b>") for n in range(2, 9)]:
            await badge.set_content(BADGE_HTML % text)
            await badge.locator("span").screenshot(path=str(WORK / f"badge_{name}.png"), omit_background=True)
        await browser.close()


def resolve(kind: str, ref, marks: dict) -> float:
    """A clip bound -> seconds in its recording."""
    if kind == "v":
        return float(ref)
    name, _, plus = str(ref).partition("+")
    return marks[name] + (float(plus) if plus else 0.0)


def build() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    recordings = {"v": (OUT / "dashboard.mp4", json.loads((OUT / "marks.json").read_text())),
                  "c": (OUT / "dashboard_coach.mp4", json.loads((OUT / "marks_coach.json").read_text()))}
    recordings["m"] = recordings["v"]
    timings = speak()
    asyncio.run(render_stills())
    segs, srt, clock = [], [], 0.0
    for s in SCENES:
        sid = s["id"]
        cues = timings.get(sid, [])
        voice = cues[-1][1] if cues else 0.0
        dur = round(s.get("hold") or (LEAD_S + voice + TAIL_S), 3)
        seg = WORK / f"seg_{sid}.mp4"
        audio = (["-i", str(WORK / "tts" / f"{sid}.wav")] if cues else
                 ["-f", "lavfi", "-t", str(dur), "-i", "anullsrc=r=24000:cl=mono"])
        afilt = f"[1:a]adelay={int(LEAD_S * 1000)},apad,atrim=0:{dur},aresample=48000,aformat=channel_layouts=stereo[a]"
        if "clip" in s:
            kind, a, b = s["clip"]
            src, marks = recordings[kind]
            start, end = resolve(kind, a, marks), resolve(kind, b, marks)
            speed = (end - start) / dur
            badges = [WORK / "badge_replay.png"]
            # tpad holds the last frame if rounding leaves the clip a few frames short
            vf = (f"[0:v]setpts=(PTS-STARTPTS)/{speed:.4f},fps={FPS},tpad=stop_mode=clone:stop_duration=2,"
                  f"trim=duration={dur}[b0];[b0][2:v]overlay=W-w-22:18[b1]")
            if speed >= 1.5:
                badges.append(WORK / f"badge_x{min(8, max(2, round(speed)))}.png")
                vf += ";[b1][3:v]overlay=22:18[v]"
            else:
                vf = vf.replace("[b1]", "[v]")
            inputs = ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(src), *audio]
            for bpath in badges:
                inputs += ["-i", str(bpath)]
            ff(*inputs, "-filter_complex", vf + ";" + afilt, "-map", "[v]", "-map", "[a]", "-t", str(dur),
               "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", str(seg))
            print(f"{sid:8s} clip {start:6.1f}-{end:6.1f} s  x{speed:.2f}  -> {dur:.1f} s")
        else:
            n = int(dur * FPS)
            zoom = "" if "card" in s else f",zoompan=z='1+0.04*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS}"
            vf = (f"[0:v]scale=3840:2160{zoom},scale=1920:1080,format=yuv420p,"
                  f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, dur - 0.3):.2f}:d=0.3[v]")
            ff("-loop", "1", "-framerate", str(FPS), "-t", str(dur), "-i", str(WORK / f"{sid}.png"), *audio,
               "-filter_complex", vf + ";" + afilt, "-map", "[v]", "-map", "[a]", "-t", str(dur),
               "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", str(seg))
            print(f"{sid:8s} still -> {dur:.1f} s")
        for c0, c1, text in cues:
            srt.append((clock + LEAD_S + c0, clock + LEAD_S + c1, text))
        segs.append(seg)
        clock += dur

    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    (OUT / "far-point-demo.srt").write_text(
        "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(srt, 1)), encoding="utf-8")
    (WORK / "segs.txt").write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
    (WORK / "captions.srt").write_bytes((OUT / "far-point-demo.srt").read_bytes())
    style = ("FontName=Segoe UI,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H70101820,"
             "BorderStyle=3,Outline=5,Shadow=0,MarginV=22,MarginL=60,MarginR=60")
    final = OUT / "far-point-demo.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", "segs.txt", "-vf", f"subtitles=captions.srt:force_style='{style}'",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    str(final)],
                   cwd=WORK, check=True)
    print(f"saved {final}  {probe_len(final):.1f} s")


if __name__ == "__main__":
    build()
