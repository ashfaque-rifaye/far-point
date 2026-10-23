# Notes for agents working in this repo

## Layout

- `web/` holds the dashboard front end (Vite + React + TypeScript). It is the only UI: do not build a second one (no `myrmidon/dashboard/static/index.html` or similar). Rebuild `web/dist` after changing `web/src` (`npm run build`, npm cache on `E:\myrmidon-runtime\npm-cache`) and commit it, because the backend serves it.
- The Python package `myrmidon/`, `patterns/`, `eval/`, `results/`, `scripts/`, `tests/` hold the agent.

## How the backend and the UI connect

- The backend (FastAPI) serves the built UI from `web/dist` at `http://127.0.0.1:8765/`.
- It exposes one WebSocket at `ws://127.0.0.1:8765/ws` that follows the contract in `docs/ui-contract.md`. The TypeScript types live in `web/src/contract.ts` and the JSON Schema in `web/contract.schema.json`.
- Every message uses the envelope `{ "v": 1, "type": "...", "t": <epoch ms>, "data": { ... } }`.
- Server-to-client events: `hello`, `signals` (5-10 Hz), `decision` (every 2-3 s), `action`, `verification`, `break`, `doctrine`, `proposal`, `stats`, `report`, `email_draft`, `confirm_request`, `toast`.
- Client-to-server commands (`"type": "cmd"`): `set_eye_description`, `approve_doctrine`, `approve_proposal`, `reject_proposal`, `start_calibration`, `request_report`, `draft_exam_email`, `confirm`, `pause_camera`, `skip_break`.
- If the contract files are not written yet, follow this summary. Once they exist, they are the source of truth.

## Ports

- Dashboard and WebSocket: 8765
- Strands Decider server: 8099, bound to 127.0.0.1 only

## Git hygiene

- `web/.gitignore` keeps `web/node_modules` and build caches out of git. Never commit `node_modules`, `.venv`, camera frames, recordings, model weights, `.env` files or credentials.
