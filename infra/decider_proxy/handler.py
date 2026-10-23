"""Public front door for the hosted Decider: a Lambda Function URL in front of a SageMaker Serverless endpoint.

The browser cannot sign SageMaker calls, so this small function (128 MB, inside Lambda's always-free
tier) forwards {"state", "questions"} to the endpoint and returns its answers. It also holds the cost
guard: SageMaker bills per second of inference, so every call's duration is added to a daily counter
and an all-time counter in DynamoDB; past either cap it answers 429 without calling SageMaker.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError

ENDPOINT = os.environ["ENDPOINT"]
TABLE = os.environ.get("USAGE_TABLE", "myrmidon-decider-usage")
DAILY_SECONDS = float(os.environ.get("DAILY_SECONDS", "600"))
TOTAL_SECONDS = float(os.environ.get("TOTAL_SECONDS", "6500"))
MAX_STATE_CHARS, MAX_QUESTIONS = 6000, 12

_ddb = boto3.client("dynamodb")
_sm = boto3.client("sagemaker-runtime", config=Config(read_timeout=70, retries={"max_attempts": 0}))


def _used(key: str) -> float:
    item = _ddb.get_item(TableName=TABLE, Key={"day": {"S": key}}).get("Item") or {}
    return float(item.get("seconds", {}).get("N", "0"))


def _add(key: str, seconds: float) -> None:
    _ddb.update_item(TableName=TABLE, Key={"day": {"S": key}}, UpdateExpression="ADD seconds :s, calls :one",
                     ExpressionAttributeValues={":s": {"N": f"{seconds:.3f}"}, ":one": {"N": "1"}})


def _reply(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, context):
    method = (event.get("requestContext", {}).get("http", {}) or {}).get("method", "POST")
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    used_day, used_total = _used(day), _used("total")
    if method == "GET":
        return _reply(200, {"status": "ok", "endpoint": ENDPOINT, "day": day, "seconds_today": round(used_day, 1),
                            "daily_seconds": DAILY_SECONDS, "seconds_total": round(used_total, 1),
                            "total_seconds": TOTAL_SECONDS})
    if method != "POST":
        return _reply(405, {"error": "use POST"})
    if used_day >= DAILY_SECONDS or used_total >= TOTAL_SECONDS:
        which = "daily" if used_day >= DAILY_SECONDS else "total"
        return _reply(429, {"error": "limit", "detail": f"The hosted Decider's {which} free budget is used up."
                                                        + (" It resets at 00:00 UTC." if which == "daily" else "")})
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
        if not isinstance(body.get("state"), str) or len(body["state"]) > MAX_STATE_CHARS:
            raise ValueError("state must be text under 6000 characters")
        if not isinstance(body.get("questions"), dict) or not 0 < len(body["questions"]) <= MAX_QUESTIONS:
            raise ValueError("1 to 12 questions")
    except (ValueError, TypeError) as e:
        return _reply(400, {"error": "bad_request", "detail": str(e)})
    started = time.perf_counter()
    try:
        r = _sm.invoke_endpoint(EndpointName=ENDPOINT, ContentType="application/json",
                                Body=json.dumps({"state": body["state"], "questions": body["questions"]}))
        payload = json.loads(r["Body"].read())
        return _reply(200, payload)
    except ClientError as e:
        msg = str(e)
        if "not found" in msg.lower() or "Could not find endpoint" in msg:
            # The endpoint is created once the account's serverless memory limit allows 6 GB.
            return _reply(503, {"error": "not_deployed", "detail": "The hosted Decider endpoint is not running yet."})
        # A cold start loads the model (about a minute); the browser retries.
        return _reply(503, {"error": "warming_up", "detail": msg[:300]})
    except ReadTimeoutError as e:
        return _reply(503, {"error": "warming_up", "detail": str(e)[:300]})
    finally:
        spent = time.perf_counter() - started
        _add(day, spent)
        _add("total", spent)
