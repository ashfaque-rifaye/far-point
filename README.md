# Far Point

An agentic vision-habits coach. A webcam measures viewing distance and squint on-device (MediaPipe), Strands Decider 2B makes fast, repeated reflex decisions locally, and Amazon Bedrock (Nova) handles the coaching language.

Status: work in progress. The Phase 1 feasibility spike is done; Decider runs text-only. See `eval/SPIKE_RESULTS.md`.

## Layout

| Path | Purpose |
|---|---|
| `farpoint/` | Agent: `sense`, `decide`, `act`, `verify`, `coach`, `dashboard`, `app` entrypoint |
| `patterns/reflex_gate/` | Reusable Decider 2B decision pattern |
| `eval/` | Evaluation harness |
| `results/` | Measured results |
| `docs/` | Documentation |
| `scripts/` | Setup and calibration scripts |
| `tests/` | pytest suite |

## Setup (Windows, PowerShell)

```powershell
$env:UV_CACHE_DIR="E:\farpoint-runtime\uv-cache"; $env:HF_HOME="E:\farpoint-runtime\hf"
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
python scripts/calibrate.py --distance-cm 50
```

Not a medical device. Far Point does not diagnose or treat eye conditions.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
