"""Coaching language via Amazon Bedrock (Nova) through a Strands Agent."""
from __future__ import annotations

import os

COACH_MODEL = os.environ.get("FARPOINT_COACH_MODEL", "us.amazon.nova-lite-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")


def make_agent(system_prompt: str = "You are Far Point, a brief, friendly eye-habits coach. Not a doctor."):
    from strands import Agent
    from strands.models import BedrockModel
    model = BedrockModel(model_id=COACH_MODEL, region_name=REGION, max_tokens=200)
    return Agent(model=model, system_prompt=system_prompt, callback_handler=None)
