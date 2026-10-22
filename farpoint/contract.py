"""JSON Schema helpers for the UI contract (`web/contract.schema.json`)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "web" / "contract.schema.json"


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def validator(defname: str) -> Draft202012Validator:
    schema = load_schema()
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{defname}"})


def errors(obj: dict, defname: str) -> list[str]:
    return [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator(defname).iter_errors(obj)]


def is_valid(obj: dict, defname: str) -> bool:
    return validator(defname).is_valid(obj)


def validate_event(env: dict) -> None:
    """Raise jsonschema.ValidationError if `env` is not a valid ServerEvent."""
    validator("ServerEvent").validate(env)


def validate_command(cmd: dict) -> None:
    """Raise jsonschema.ValidationError if `cmd` is not a valid ClientCommand."""
    validator("ClientCommand").validate(cmd)
