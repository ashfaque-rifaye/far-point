# Submission kit (Agent Experience Hackathon: Strands Decider)

Deadline: **Oct 23, 2026, 11:59 PM PT** (Oct 24, 12:29 PM IST). A submission missing any of the three parts below is not judged.

## Pass/fail checklist

| # | Requirement | Status |
|---|---|---|
| 1 | Working agent on AWS that uses Strands Decider 2B for a meaningful decision, paired with Amazon Bedrock | Done: local Decider decides tool selection every 2.5 s; Amazon Nova Lite on Bedrock (us-east-1) does rulebook, reports, proposals, email draft and escalation |
| 2 | Article published on AWS Builder Center describing the agent and the decision | Draft ready: [`ARTICLE.md`](ARTICLE.md). **You publish it** |
| 3 | Public repo, OSI license, agent source + clearly labelled reusable decision pattern | Done: https://github.com/ashfaque-rifaye/far-point (Apache-2.0), `patterns/reflex_gate/` headed "REUSABLE DECISION PATTERN" |
| 4 | Video under 3 minutes, public on YouTube/Vimeo/Facebook Video/Youku, no unlicensed music or trademarks | Built: `far-point-demo.mp4` (see "Video upload" below), no music. **You upload it (Public)** |
| 5 | Tags `#strands-decider-2b` and one pattern tag | Use `#strands-decider-2b` `#tool-selection` |
| 6 | Original, not previously published | Repo created Oct 22, 2026 |

## Copy-paste fields

**Project name:** Far Point

**One-line description:** A screen that adapts to your eyes: a local Strands Decider 2B decides every 2.5 s which reversible change helps (bigger text, dark mode, a camera-verified far-look break), Amazon Nova on Bedrock writes your rulebook and optometrist report, and no face image ever leaves the laptop.

**Short description (about 100 words):**
Far Point watches how you use your eyes at the screen and adapts the screen to you. The webcam measures viewing distance, eye opening and blinks on the laptop. Every 2.5 s a local Strands Decider 2B answers one yes/no per rule in your rulebook; code applies the priority order; a Strands Agent runs one reversible tool and Strands interventions stop it at bad moments. Thirty seconds later the camera checks whether it helped. Amazon Nova Lite writes the rulebook from your own words, numbers-only reports and an exam-email draft. On preregistered tests the hybrid matched Nova alone at 100%, 4.5x faster and with 11x fewer tokens.

**Tags:** `#strands-decider-2b` `#tool-selection`

**Repo:** https://github.com/ashfaque-rifaye/far-point

## Video upload (YouTube, Public)

The built video is `E:\farpoint-runtime\recordings\video\far-point-demo.mp4` with captions in `far-point-demo.srt` next to it (rebuild: `scripts/video_record_scenes.py`, then `scripts/video_build.py`; see `VIDEO_SCRIPT.md`).

**Title:** Far Point: a screen that adapts to your eyes (Strands Decider 2B + Amazon Bedrock)

**Description:**
Far Point is a Windows laptop agent. The webcam measures viewing distance and eye opening on the laptop; every 2.5 s a local Strands Decider 2B answers one yes/no per rule in your rulebook, code applies the priority order, and a Strands Agent runs one reversible tool (bigger text, dark mode, a camera-verified far-look break). Strands interventions hold breaks during calls. Amazon Nova Lite on Bedrock writes the rulebook from your words and a numbers-only report, and is asked only when a rule is unsure. No face image leaves the laptop.

Dashboard footage is a synthetic trace replayed through the real agent (real Decider, real Nova, dry-run desktop changes). Narration is spoken by Kokoro TTS on the laptop. Not a medical device.

Code (Apache-2.0) and the reusable Reflex Gate pattern: https://github.com/ashfaque-rifaye/far-point
#strands-decider-2b #tool-selection

**Settings:** Visibility Public. "No, it's not made for kids". Upload `far-point-demo.srt` under Subtitles as English.

## Images to upload with the article (all in `docs/images/`)

| File | Use |
|---|---|
| `cover.png` | Article cover / header |
| `architecture.png` | Architecture section |
| `decision-loop.png` | "The decision handed to Decider 2B" section |
| `dashboard-now-too-close.png`, `dashboard-now-worked.png` | The glasses-off moment, before and after |
| `dashboard-break.png` | Camera-verified break |
| `dashboard-reflex.png` | Reflex log |

The dashboard screenshots come from the in-browser demo story (scripted numbers). The article says so under the images; keep that sentence.

## Order of work on submission day

1. Run the guided webcam session (`.\scripts\human_session.ps1 -Parts ab`, about 4 minutes): calibration and the live lean-in trial. It writes `results/human_*.json`.
2. Upload `far-point-demo.mp4` to YouTube as **Public** with the title, description and captions above. (Optional: record your own take with `VIDEO_SCRIPT.md` instead.)
3. Publish the article on Builder Center from `ARTICLE.md`, upload the images above, add both tags, paste the repo and video links.
4. Put the article and video links into the README "Links" section and push.
5. Submit the project on the hackathon page with the article, repo and video links before the deadline.
