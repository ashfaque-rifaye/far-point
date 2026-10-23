# Far Point demo video (target 2:45, hard limit 3:00)

## The built cut

`far-point-demo.mp4` is produced without a camera or a microphone:

1. `uv run --no-project --with playwright python scripts/video_record_scenes.py` starts the backend in replay mode with the real local Decider and Amazon Nova (dry-run desktop changes), drives Edge through the screens and captures them at 1080p, about 5 minutes. Add `--coach-only` to refilm just the rulebook and report scenes (about 1 minute).
2. `uv run --no-project --with playwright python scripts/video_build.py` speaks the narration with Kokoro TTS on the laptop (`scripts/video_tts.py`, its own environment at `E:\farpoint-runtime\tts-env`), renders the diagrams and cards, cuts the recording to the narration, speeds up long waits (labelled on screen), burns in captions and writes `far-point-demo.mp4` and `far-point-demo.srt` to `E:\farpoint-runtime\recordings\video`.

The narration and the scene list live in `SCENES` in `scripts/video_build.py`; its clip windows were picked from the recorded frames, so check them after a new take. The current cut is 2:44. Every dashboard shot carries a label saying it is a synthetic trace replayed through the real agent.

## Recording your own take

Record the screen with `scripts\record_demo.ps1`. Film the "glasses off" moments with your phone (the laptop webcam is busy measuring you, Windows lets only one app use it). No music, or only music you have the rights to. Speak the narration live or record it after; keep it under 400 words.

Before you start:

1. `.\scripts\start_decider.ps1`, wait for "ready".
2. Close the Android emulator, EA Desktop and other GPU apps.
3. `.venv\Scripts\python.exe -m farpoint.app --mode live --record`, then open http://127.0.0.1:8765/ in Edge, full screen (F11), Day theme.
4. Have a long article open in Edge in a second window, at your normal zoom.
5. Backup: if anything fails live, the same shots work with `http://127.0.0.1:8765/?demo=1` (it says DEMO on screen; say so in the voiceover).

| Time | Shot | Narration |
|---|---|---|
| 0:00-0:12 | Phone: you at the laptop at night, glasses on, then you take them off and lean in | "It's late, my glasses are off, and I've crept to 26 centimetres from the screen. I never notice." |
| 0:12-0:30 | Screen: Far Point Now screen. The pill drops to "26 cm", the dial needle goes amber/red, the drawn eye narrows | "Far Point is watching how I see. The webcam measures my distance and how open my eyes are, on this laptop. No image leaves it: that counter stays at zero." |
| 0:30-0:50 | Decision card: rule 1 bar fills to 0.9+, "Enlarge text", chip "done". Cut to the Edge article getting one step bigger | "Every two and a half seconds, Strands Decider 2B, running on my laptop GPU, answers one yes-or-no per rule in my rulebook. Rule 1 applies. A Strands agent makes the text one step larger." |
| 0:50-1:05 | Phone: you sit back. Screen: needle climbs to ~46 cm, "Did it help? 26 → 46 cm. Worked." | "It didn't tell me to sit back. It made sitting back possible. Then it checked: 26 to 46 centimetres. Worked." |
| 1:05-1:25 | Reflex log screen, open one decision to show "What the Decider read" | "Code does the arithmetic and writes each fact as a verdict. The Decider only judges the words, in about half a second. The first version asked one nine-way question and got 68 percent. One question per rule, with code applying the order, got 87.5." |
| 1:25-1:45 | Join a Teams call (or the demo's Teams segment): decision shows far-look break with "InterruptGate: deny" | "It knows when not to interrupt. During a call, a Strands intervention holds the break." |
| 1:45-2:00 | Break overlay: countdown ring, you look out of a window (phone), "verified" | "After the call: a 20-second far look. It only counts when the camera sees me look away." |
| 2:00-2:20 | Rulebook: type "I'm minus 3.5 and glare bothers me at night", Draft, then Adopt. Report screen: Nova report | "Amazon Nova on Bedrock writes my rulebook from my own words, and a report for my optometrist, from numbers only. Nothing changes until I approve it." |
| 2:20-2:38 | Results table from the README (zoomed) | "Nova Lite alone is just as accurate on our test set, but it takes 2.6 seconds and 11 times the tokens. Together: 100 percent, with Nova on one state in eight." |
| 2:38-2:45 | Repo page: patterns/reflex_gate | "The pattern is reusable: Reflex Gate, in the repo. Far Point. Not a medical device, just a kinder screen." |

Upload to YouTube as Public (or Unlisted is not enough: it must be publicly visible). Put the link in the article and the repo README.
