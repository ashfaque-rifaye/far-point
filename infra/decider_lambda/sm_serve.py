"""SageMaker entrypoint: the stock strands-decider server on :8080 (/ping and /invocations), CPU, bf16.

SageMaker Serverless allows at most 6 GB, and the engine widens a bf16 torso to fp32 on CPU (about
7 GiB), so this keeps the torso in bf16: slower per token, same answers within rounding.
SageMaker starts the container as `<entrypoint> serve`; the argument is ignored.
"""
import os

import uvicorn
from strands_decider import infer
from strands_decider.server import create_app

infer.SystemOneEngine._upcast_torso_for_cpu = lambda self: None  # stay in bf16 to fit 6 GB

app = create_app(os.environ.get("CHECKPOINT", "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"), device="cpu",
                 model_name="strands-decider-2B-qwen3.5-v1-2610 (SageMaker Serverless, CPU)")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
