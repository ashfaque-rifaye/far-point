"""Host Strands Decider 2B for the hosted Myrmidon page on SageMaker Serverless Inference (us-east-1).

Why not Lambda: this account's Lambda functions are capped at 3,008 MB and the Decider needs about
5 GB. SageMaker Serverless allows 6 GB, scales to zero (no charge while idle) and bills per second of
inference. A small proxy Lambda (128 MB, always-free tier) gives the browser a public Function URL
and keeps the spend capped (daily and all-time seconds, counted in DynamoDB). Safe to re-run.

    python scripts/deploy_decider_sagemaker.py --email you@example.com            # build + deploy
    python scripts/deploy_decider_sagemaker.py --email you@example.com --no-build
"""
import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_decider_lambda import ORIGINS, REGION, ROOT, TABLE, TAGS, build_image, ensure_role  # noqa: E402

NAME = "myrmidon-decider"
ENDPOINT = "myrmidon-decider-serverless"
PROXY = "myrmidon-decider-proxy"
MEMORY_MB = 6144
# Serverless inference at 6 GB is about $0.00012 per second (us-east-1). 6,500 s all-time is about $0.78,
# spread at most 600 s a day, so the page stays up through judging and the total stays under $1.
DAILY_SECONDS, TOTAL_SECONDS = 600, 6500


def main(email: str, build: bool, endpoint: bool = True) -> None:
    s = boto3.Session(region_name=REGION)
    account = s.client("sts").get_caller_identity()["Account"]
    ecr, sm, lam, iam, ddb = s.client("ecr"), s.client("sagemaker"), s.client("lambda"), s.client("iam"), s.client("dynamodb")
    repo_uri = ecr.describe_repositories(repositoryNames=[NAME])["repositories"][0]["repositoryUri"]
    if build:
        build_image(s, account, repo_uri, dockerfile="Dockerfile.sagemaker", tag="sagemaker")
    if endpoint:
        deploy_endpoint(s, account, repo_uri)
    deploy_proxy(s, account, email)


def deploy_endpoint(s, account: str, repo_uri: str) -> None:
    sm, iam = s.client("sagemaker"), s.client("iam")

    role = ensure_role(iam, f"{NAME}-sagemaker", "sagemaker.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"],
         "Resource": f"arn:aws:ecr:{REGION}:{account}:repository/{NAME}"},
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
                                       "cloudwatch:PutMetricData"], "Resource": "*"}]})
    stamp = time.strftime("%Y%m%d%H%M%S")
    model = f"{NAME}-{stamp}"
    sm.create_model(ModelName=model, ExecutionRoleArn=role, Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()],
                    PrimaryContainer={"Image": f"{repo_uri}:sagemaker", "Mode": "SingleModel",
                                      "Environment": {"HF_HOME": "/opt/hf", "HF_HUB_OFFLINE": "1",
                                                      "TRANSFORMERS_OFFLINE": "1"}})
    config = f"{NAME}-{stamp}"
    sm.create_endpoint_config(EndpointConfigName=config, ProductionVariants=[{
        "VariantName": "main", "ModelName": model,
        "ServerlessConfig": {"MemorySizeInMB": MEMORY_MB, "MaxConcurrency": 1}}])
    try:
        sm.describe_endpoint(EndpointName=ENDPOINT)
        sm.update_endpoint(EndpointName=ENDPOINT, EndpointConfigName=config)
    except ClientError:
        sm.create_endpoint(EndpointName=ENDPOINT, EndpointConfigName=config,
                           Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
    print("waiting for the SageMaker endpoint", ENDPOINT, flush=True)
    while True:
        status = sm.describe_endpoint(EndpointName=ENDPOINT)
        if status["EndpointStatus"] not in ("Creating", "Updating"):
            break
        time.sleep(20)
    print("endpoint", status["EndpointStatus"], status.get("FailureReason", ""), flush=True)
    if status["EndpointStatus"] != "InService":
        raise SystemExit("endpoint failed")


def deploy_proxy(s, account: str, email: str) -> None:
    lam, iam, ddb = s.client("lambda"), s.client("iam"), s.client("dynamodb")
    try:
        ddb.describe_table(TableName=TABLE)
    except ddb.exceptions.ResourceNotFoundException:
        ddb.create_table(TableName=TABLE, AttributeDefinitions=[{"AttributeName": "day", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "day", "KeyType": "HASH"}], BillingMode="PROVISIONED",
                         ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1})
        ddb.get_waiter("table_exists").wait(TableName=TABLE)

    prole = ensure_role(iam, f"{PROXY}-role", "lambda.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
         "Resource": f"arn:aws:dynamodb:{REGION}:{account}:table/{TABLE}"},
        {"Effect": "Allow", "Action": "sagemaker:InvokeEndpoint",
         "Resource": f"arn:aws:sagemaker:{REGION}:{account}:endpoint/{ENDPOINT}"}]},
        managed=["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "infra" / "decider_proxy" / "handler.py", "handler.py")
    env = {"Variables": {"ENDPOINT": ENDPOINT, "USAGE_TABLE": TABLE, "DAILY_SECONDS": str(DAILY_SECONDS),
                         "TOTAL_SECONDS": str(TOTAL_SECONDS)}}
    try:
        lam.get_function(FunctionName=PROXY)
        lam.update_function_code(FunctionName=PROXY, ZipFile=buf.getvalue())
        lam.get_waiter("function_updated_v2").wait(FunctionName=PROXY)
        lam.update_function_configuration(FunctionName=PROXY, Environment=env, Timeout=90, MemorySize=128)
    except lam.exceptions.ResourceNotFoundException:
        for attempt in range(6):
            try:
                lam.create_function(FunctionName=PROXY, Runtime="python3.12", Handler="handler.handler", Role=prole,
                                    Code={"ZipFile": buf.getvalue()}, MemorySize=128, Timeout=90, Environment=env,
                                    Description="Public front door + cost cap for the Myrmidon Decider", Tags=TAGS)
                break
            except lam.exceptions.InvalidParameterValueException as e:
                if attempt == 5:
                    raise
                print("waiting for the IAM role:", e)
                time.sleep(10)
    lam.get_waiter("function_active_v2").wait(FunctionName=PROXY)
    lam.get_waiter("function_updated_v2").wait(FunctionName=PROXY)
    cors = {"AllowOrigins": ORIGINS, "AllowMethods": ["GET", "POST"], "AllowHeaders": ["content-type"], "MaxAge": 3600}
    try:
        url = lam.create_function_url_config(FunctionName=PROXY, AuthType="NONE", Cors=cors)["FunctionUrl"]
    except lam.exceptions.ResourceConflictException:
        url = lam.update_function_url_config(FunctionName=PROXY, AuthType="NONE", Cors=cors)["FunctionUrl"]
    for sid, action, extra in (("public-url", "lambda:InvokeFunctionUrl", {"FunctionUrlAuthType": "NONE"}),
                               ("public-url-invoke", "lambda:InvokeFunction", {"InvokedViaFunctionUrl": True})):
        try:
            lam.add_permission(FunctionName=PROXY, StatementId=sid, Action=action, Principal="*", **extra)
        except lam.exceptions.ResourceConflictException:
            pass
        except Exception as e:  # noqa: BLE001
            print("permission", sid, "skipped:", e)

    budgets = s.client("budgets")
    budget = {"BudgetName": "myrmidon-hosted-decider", "BudgetType": "COST", "TimeUnit": "MONTHLY",
              "BudgetLimit": {"Amount": "1", "Unit": "USD"},
              "CostFilters": {"Service": ["AWS Lambda", "Amazon EC2 Container Registry (ECR)", "AWS CodeBuild",
                                          "Amazon DynamoDB", "AWS Amplify", "Amazon SageMaker"]}}
    try:
        budgets.update_budget(AccountId=account, NewBudget=budget)
        print("budget alert updated to include SageMaker")
    except budgets.exceptions.NotFoundException:
        alerts = [{"Notification": {"NotificationType": t, "ComparisonOperator": "GREATER_THAN", "Threshold": 100,
                                    "ThresholdType": "PERCENTAGE"},
                   "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}]} for t in ("ACTUAL", "FORECASTED")]
        budgets.create_budget(AccountId=account, Budget=budget, NotificationsWithSubscribers=alerts)
        print("budget alert: $1/month ->", email)

    (ROOT / "web" / ".env.production").write_text(f"VITE_DECIDER_URL={url}\n", encoding="utf-8")
    print("Decider URL:", url)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--proxy-only", action="store_true",
                    help="only the capped proxy (the page falls back to code rules until the endpoint exists)")
    a = ap.parse_args()
    main(a.email, not a.no_build and not a.proxy_only, endpoint=not a.proxy_only)
