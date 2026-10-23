# Submission kit (Agent Experience Hackathon: Strands Decider)

Deadline: **Oct 23, 2026, 11:59 PM PT** (Oct 24, 12:29 PM IST). A submission missing any of the three parts below is not judged.

## Pass/fail checklist

| # | Requirement | Status |
|---|---|---|
| 1 | Working agent on AWS that uses Strands Decider 2B for a meaningful decision, paired with Amazon Bedrock | Done: local Decider decides tool selection every 2.5 s; Amazon Nova Lite on Bedrock (us-east-1) does rulebook, reports, proposals, email draft and escalation |
| 2 | Article published on AWS Builder Center describing the agent and the decision | Draft ready: [`ARTICLE.md`](ARTICLE.md). **You publish it** |
| 3 | Public repo, OSI license, agent source + clearly labelled reusable decision pattern | Done: https://github.com/ashfaque-rifaye/myrmidon (Apache-2.0), `patterns/reflex_gate/` headed "REUSABLE DECISION PATTERN" |
| 4 | Video under 3 minutes, public on YouTube/Vimeo/Facebook Video/Youku, no unlicensed music or trademarks | Built: `myrmidon-demo.mp4` (see "Video upload" below), no music. **You upload it (Public)** |
| 5 | Tags `#strands-decider-2b` and one pattern tag | Use `#strands-decider-2b` `#tool-selection` |
| 6 | Original, not previously published | Repo created Oct 22, 2026 |

## Copy-paste fields

**Project name:** Myrmidon

**One-line description:** A screen that adapts to your eyes: a local Strands Decider 2B decides every 2.5 s which reversible change helps (bigger text, dark mode, a camera-verified far-look break), Amazon Nova on Bedrock writes your rulebook and optometrist report, and no face image ever leaves the laptop.

**Short description (about 100 words):**
Myrmidon watches how you use your eyes at the screen and adapts the screen to you. The webcam measures viewing distance, eye opening and blinks on the laptop. Every 2.5 s a local Strands Decider 2B answers one yes/no per rule in your rulebook; code applies the priority order; a Strands Agent runs one reversible tool and Strands interventions stop it at bad moments. Thirty seconds later the camera checks whether it helped. Amazon Nova Lite writes the rulebook from your own words, numbers-only reports and an exam-email draft. On preregistered tests the hybrid matched Nova alone at 100%, about 5x faster (p50 0.46 s vs 2.57 s) and with 11x fewer tokens.

**Note on the name and repo:** the project was renamed from "Far Point" to **Myrmidon** on Oct 23. The repo moved to https://github.com/ashfaque-rifaye/myrmidon; GitHub redirects the old `far-point` URL, so a link already submitted keeps working. Update the project name on the hackathon page if it still says Far Point.

**Tags:** `#strands-decider-2b` `#tool-selection`

**Repo:** https://github.com/ashfaque-rifaye/myrmidon

**Endpoint or live demo:** https://main.d15fdmq2raifi0.amplifyapp.com/ (the dashboard on AWS Amplify Hosting, playing its scripted demo story; republish with `scripts/deploy_demo.py`)

## Video upload (YouTube, Public)

The built video is `E:\myrmidon-runtime\recordings\video\myrmidon-demo.mp4` with captions in `myrmidon-demo.srt` next to it (rebuild: `scripts/video_record_scenes.py`, then `scripts/video_build.py`; see `VIDEO_SCRIPT.md`).

**Title:** Myrmidon: a screen that adapts to your eyes (Strands Decider 2B + Amazon Bedrock)

**Description:**
Myrmidon is a Windows laptop agent built for the Agent Experience Hackathon (#tool-selection). Every 2.5 s, Strands Decider 2B on the laptop GPU decides which tool, if any, should run: one typed yes/no question per rule in your rulebook, all in one request, each answered with a calibrated probability in about 0.5 s. Code applies the priority order; a Strands Agent runs the tool behind two Strands intervention handlers (InterruptGate holds breaks during calls); the camera checks 30 s later whether it helped. Amazon Nova Lite on Bedrock writes the rulebook from your own words, answers only when the Decider is unsure, and writes a numbers-only report. No face image leaves the laptop.

Measured on 72 preregistered states: 100% tool-selection accuracy, same as Nova Lite alone, at 0.46 s instead of 2.57 s and with 11x fewer tokens.

0:00 The problem
0:10 How it reads your eyes
0:34 Architecture: Decider 2B on the laptop, Bedrock for language
1:01 The decision handed to Decider 2B (#tool-selection)
1:33 Live replay: rule 1 fires, verified, InterruptGate holds a break
2:09 Measured: accuracy, latency, tokens
2:33 Reflex Gate: the reusable pattern
2:48 What the hackathon asks for, and where it is

Dashboard footage is a synthetic trace replayed through the real agent (real Decider, real Nova, dry-run desktop changes). Explainer scenes are animated diagrams. Narration is spoken by Kokoro TTS on the laptop. Not a medical device.

Code (Apache-2.0) and the reusable Reflex Gate pattern: https://github.com/ashfaque-rifaye/myrmidon
#strands-decider-2b #tool-selection

**Settings:** Visibility Public. "No, it's not made for kids". Upload `myrmidon-demo.srt` under Subtitles as English.

## Images to upload with the article (all in `docs/images/`)

| File | Use |
|---|---|
| `myrmidon-cover-1200x675.png` | Builder Center cover (1200x675, no text; source `cover-clean.html`) |
| `cover.png` | Header image with title, for places that want text |
| `architecture.png` | Architecture section |
| `decision-loop.png` | "The decision handed to Decider 2B" section |
| `results.png` | Results section |
| `reflex-gate.png` | "The reusable pattern" section |
| `dashboard-now-too-close.png`, `dashboard-now-worked.png` | The glasses-off moment, before and after |
| `dashboard-break.png` | Camera-verified break |
| `dashboard-reflex.png` | Reflex log |

The dashboard screenshots come from the in-browser demo story (scripted numbers). The article says so under the images; keep that sentence.

## Order of work on submission day

1. Run the guided webcam session (`.\scripts\human_session.ps1 -Parts ab`, about 4 minutes): calibration and the live lean-in trial. It writes `results/human_*.json`.
2. Upload `myrmidon-demo.mp4` to YouTube as **Public** with the title, description and captions above. (Optional: record your own take with `VIDEO_SCRIPT.md` instead.)
3. Publish the article on Builder Center from `ARTICLE.md`, upload the images above, add both tags, paste the repo and video links.
4. Put the article and video links into the README "Links" section and push.
5. Submit the project on the hackathon page with the article, repo and video links before the deadline.
