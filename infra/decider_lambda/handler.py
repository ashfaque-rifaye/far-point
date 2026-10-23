"""Lambda handler: Strands Decider 2B on CPU behind a public Function URL, with a daily compute cap.

POST the same JSON as the local server's /v1/systemone ({"state": ..., "questions": {...}}) and get the
same answers back. GET returns health and today's usage.

Cost guard: every call adds its wall time (including a cold start's model load) to a per-day
counter in DynamoDB. Past DAILY_SECONDS the function answers 429 without touching the model, so
a whole month stays inside Lambda's always-free compute allowance. Reserved concurrency 1 (set
at deploy) means only one copy ever runs.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import time

import boto3

CHECKPOINT = os.environ.get("CHECKPOINT", "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610")
TABLE = os.environ.get("USAGE_TABLE", "myrmidon-decider-usage")
DAILY_SECONDS = float(os.environ.get("DAILY_SECONDS", "1200"))
MAX_STATE_CHARS, MAX_QUESTIONS = 6000, 12

_ddb = boto3.client("dynamodb")
_engine = None


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def _used(day: str) -> float:
    item = _ddb.get_item(TableName=TABLE, Key={"day": {"S": day}}).get("Item") or {}
    return float(item.get("seconds", {}).get("N", "0"))


def _add(day: str, seconds: float) -> None:
    _ddb.update_item(TableName=TABLE, Key={"day": {"S": day}},
                     UpdateExpression="ADD seconds :s, calls :one",
                     ExpressionAttributeValues={":s": {"N": f"{seconds:.3f}"}, ":one": {"N": "1"}})


def _engine_get():
    global _engine
    if _engine is None:
        import torch
        from strands_decider.infer import EngineConfig, SystemOneEngine
        from strands_decider.modeling import StrandsDeciderModel

        torch.set_num_threads(os.cpu_count() or 2)
        model = StrandsDeciderModel.load(CHECKPOINT)
        _engine = SystemOneEngine(model, EngineConfig(device="cpu", use_prefix_cache=True,
                                                      model_name="strands-decider-2B-qwen3.5-v1-2610 (Lambda CPU)"))
    return _engine


def _reply(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "POST")
    day = _today()
    if method == "GET":
        return _reply(200, {"status": "ok", "loaded": _engine is not None, "day": day,
                            "seconds_used": round(_used(day), 1), "daily_seconds": DAILY_SECONDS})
    if method != "POST":
        return _reply(405, {"error": "use POST"})
    if _used(day) >= DAILY_SECONDS:
        return _reply(429, {"error": "daily_limit", "detail": "The free daily budget for the hosted Decider is used up. "
                                                              "It resets at 00:00 UTC."})
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
        state, questions = body["state"], body["questions"]
        if not isinstance(state, str) or len(state) > MAX_STATE_CHARS:
            raise ValueError("state must be text under 6000 characters")
        if not isinstance(questions, dict) or not 0 < len(questions) <= MAX_QUESTIONS:
            raise ValueError("1 to 12 questions")
    except (ValueError, KeyError, TypeError) as e:
        return _reply(400, {"error": "bad_request", "detail": str(e)})

    from strands_decider.schema import SystemOneRequest

    started = time.perf_counter()
    cold = _engine is None
    try:
        engine = _engine_get()
        t0 = time.perf_counter()
        response = engine.evaluate(SystemOneRequest(state=state, questions=questions))
        latency_ms = (time.perf_counter() - t0) * 1000
    except ValueError as e:
        return _reply(422, {"error": "unprocessable", "detail": str(e)})
    finally:
        _add(day, time.perf_counter() - started)
    payload = response.model_dump()
    payload.update({"latency_ms": round(latency_ms, 1), "cold_start": cold})
    return _reply(200, payload)
