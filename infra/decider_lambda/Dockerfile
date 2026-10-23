# Strands Decider 2B on AWS Lambda (CPU, x86_64), for the hosted Myrmidon page.
# Built by AWS CodeBuild (scripts/deploy_decider_lambda.py); the weights are baked in so a cold
# start never downloads anything.
FROM public.ecr.aws/lambda/python:3.12

ENV HF_HOME=/opt/hf \
    SETUPTOOLS_SCM_PRETEND_VERSION=0.2.1 \
    PIP_NO_CACHE_DIR=1

RUN pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install "transformers==5.20.2" boto3 \
      "strands-decider @ https://github.com/strands-labs/strands-decider/archive/d942e5515db750f80a51032629ec312455a87976.zip"

# The adapter + head, and the Qwen3.5-2B base it was trained on.
RUN python -c "from huggingface_hub import snapshot_download as s; \
s('StrandsAgents/strands-decider-2B-qwen3.5-v1-2610'); \
s('Qwen/Qwen3.5-2B-Base', revision='main', allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja'])"

ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
COPY handler.py ${LAMBDA_TASK_ROOT}/
CMD ["handler.handler"]
