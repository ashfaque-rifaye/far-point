"""Deploy Strands Decider 2B to AWS Lambda for the hosted Myrmidon page (us-east-1). Safe to re-run.

Creates, if missing: an ECR repository (keeps only the newest image), a private S3 bucket for the
build source, a CodeBuild project that builds infra/decider_lambda into an image, a DynamoDB table
for the daily usage counter (provisioned 1/1, inside the always-free tier), the Lambda function
(10 GB, CPU), its public Function URL (CORS: the Amplify page and local dev), reserved concurrency 1
when the account allows it, and a $1/month AWS Budget alert for the services this uses.

    python scripts/deploy_decider_lambda.py --email you@example.com          # build + deploy
    python scripts/deploy_decider_lambda.py --email you@example.com --no-build
Prints the Function URL; the dashboard reads it from web/.env.production (VITE_DECIDER_URL).
"""
import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "infra" / "decider_lambda"
REGION = "us-east-1"
NAME = "myrmidon-decider"
TABLE = "myrmidon-decider-usage"
ORIGINS = ["https://main.d15fdmq2raifi0.amplifyapp.com", "http://127.0.0.1:5173", "http://localhost:5173",
           "http://127.0.0.1:4173", "http://localhost:4173"]  # the hosted page, vite dev and vite preview
TAGS = {"project": "myrmidon"}
DAILY_SECONDS = 1200  # ~12,000 GB-s/day at 10 GB: a 31-day month stays under the 400,000 GB-s free tier


def ensure_role(iam, name: str, service: str, policy: dict, managed: list[str] = ()) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": service},
                                                     "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust),
                              Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])["Role"]["Arn"]
        time.sleep(10)  # IAM propagation
    iam.put_role_policy(RoleName=name, PolicyName=f"{name}-inline", PolicyDocument=json.dumps(policy))
    for m in managed:
        iam.attach_role_policy(RoleName=name, PolicyArn=m)
    time.sleep(15)  # policies take a few seconds to apply to sessions of the role
    return arn


def build_image(s, account: str, repo_uri: str, dockerfile: str = "Dockerfile", tag: str = "latest") -> None:
    s3, cb, iam = s.client("s3"), s.client("codebuild"), s.client("iam")
    bucket = f"myrmidon-build-{account}-use1"
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        s3.create_bucket(Bucket=bucket)
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SRC.iterdir():
            if f.is_file():
                z.write(f, f.name)
    s3.put_object(Bucket=bucket, Key="decider_lambda.zip", Body=buf.getvalue())
    role = ensure_role(iam, f"{NAME}-codebuild", "codebuild.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": "*"},
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:GetObjectVersion"], "Resource": f"arn:aws:s3:::{bucket}/*"},
        {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Effect": "Allow", "Action": ["ecr:BatchCheckLayerAvailability", "ecr:CompleteLayerUpload",
                                       "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
                                       "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
         "Resource": f"arn:aws:ecr:{REGION}:{account}:repository/{NAME}"}]})
    project = dict(name=f"{NAME}-image", source={"type": "S3", "location": f"{bucket}/decider_lambda.zip"},
                   artifacts={"type": "NO_ARTIFACTS"}, serviceRole=role, timeoutInMinutes=60,
                   environment={"type": "LINUX_CONTAINER", "computeType": "BUILD_GENERAL1_SMALL",
                                "image": "aws/codebuild/amazonlinux-x86_64-standard:5.0", "privilegedMode": True,
                                "environmentVariables": [{"name": "REPO_URI", "value": repo_uri}]})
    try:
        cb.create_project(**project, tags=[{"key": k, "value": v} for k, v in TAGS.items()])
    except cb.exceptions.ResourceAlreadyExistsException:
        cb.update_project(**project)
    build_id = cb.start_build(projectName=project["name"], environmentVariablesOverride=[
        {"name": "DOCKERFILE", "value": dockerfile}, {"name": "TAG", "value": tag}])["build"]["id"]
    print(f"building {dockerfile} -> :{tag} (CodeBuild)", build_id, flush=True)
    while True:
        b = cb.batch_get_builds(ids=[build_id])["builds"][0]
        if b["buildStatus"] != "IN_PROGRESS":
            break
        time.sleep(20)
    print("build", b["buildStatus"], f"{(b['endTime'] - b['startTime']).total_seconds() / 60:.1f} min", flush=True)
    if b["buildStatus"] != "SUCCEEDED":
        raise SystemExit("image build failed; see the CodeBuild logs for " + build_id)


def main(email: str, build: bool) -> None:
    s = boto3.Session(region_name=REGION)
    account = s.client("sts").get_caller_identity()["Account"]
    ecr, ddb, lam, iam = s.client("ecr"), s.client("dynamodb"), s.client("lambda"), s.client("iam")

    try:
        repo_uri = ecr.describe_repositories(repositoryNames=[NAME])["repositories"][0]["repositoryUri"]
    except ecr.exceptions.RepositoryNotFoundException:
        repo_uri = ecr.create_repository(repositoryName=NAME, tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])[
            "repository"]["repositoryUri"]
    ecr.put_lifecycle_policy(repositoryName=NAME, lifecyclePolicyText=json.dumps({"rules": [{
        "rulePriority": 1, "description": "keep the two newest images (Lambda and SageMaker variants)",
        "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 2},
        "action": {"type": "expire"}}]}))
    if build:
        build_image(s, account, repo_uri)

    try:
        ddb.describe_table(TableName=TABLE)
    except ddb.exceptions.ResourceNotFoundException:
        ddb.create_table(TableName=TABLE, AttributeDefinitions=[{"AttributeName": "day", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "day", "KeyType": "HASH"}], BillingMode="PROVISIONED",
                         ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
                         Tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
        ddb.get_waiter("table_exists").wait(TableName=TABLE)

    role = ensure_role(iam, f"{NAME}-lambda", "lambda.amazonaws.com", {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
         "Resource": f"arn:aws:dynamodb:{REGION}:{account}:table/{TABLE}"}]},
        managed=["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"])
    image = f"{repo_uri}:latest"
    env = {"Variables": {"USAGE_TABLE": TABLE, "DAILY_SECONDS": str(DAILY_SECONDS), "HF_HOME": "/opt/hf",
                         "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}}
    try:
        lam.get_function(FunctionName=NAME)
        lam.update_function_code(FunctionName=NAME, ImageUri=image)
        lam.get_waiter("function_updated_v2").wait(FunctionName=NAME)
        lam.update_function_configuration(FunctionName=NAME, MemorySize=10240, Timeout=300, Environment=env)
    except lam.exceptions.ResourceNotFoundException:
        for attempt in range(6):
            try:
                lam.create_function(FunctionName=NAME, PackageType="Image", Code={"ImageUri": image}, Role=role,
                                    MemorySize=10240, Timeout=300, Architectures=["x86_64"], Environment=env,
                                    Description="Strands Decider 2B on CPU for the hosted Myrmidon page", Tags=TAGS)
                break
            except lam.exceptions.InvalidParameterValueException as e:  # role not assumable yet
                if attempt == 5:
                    raise
                print("waiting for the IAM role:", e)
                time.sleep(10)
    lam.get_waiter("function_active_v2").wait(FunctionName=NAME)
    lam.get_waiter("function_updated_v2").wait(FunctionName=NAME)

    try:
        lam.put_function_concurrency(FunctionName=NAME, ReservedConcurrentExecutions=1)
        print("reserved concurrency: 1")
    except ClientError as e:  # accounts with a 10-concurrency quota cannot reserve any
        print("reserved concurrency not set:", e.response["Error"]["Message"])

    cors = {"AllowOrigins": ORIGINS, "AllowMethods": ["GET", "POST"], "AllowHeaders": ["content-type"], "MaxAge": 3600}
    try:
        url = lam.create_function_url_config(FunctionName=NAME, AuthType="NONE", Cors=cors)["FunctionUrl"]
    except lam.exceptions.ResourceConflictException:
        url = lam.update_function_url_config(FunctionName=NAME, AuthType="NONE", Cors=cors)["FunctionUrl"]
    for sid, action, extra in (("public-url", "lambda:InvokeFunctionUrl", {"FunctionUrlAuthType": "NONE"}),
                               ("public-url-invoke", "lambda:InvokeFunction", {"InvokedViaFunctionUrl": True})):
        try:
            lam.add_permission(FunctionName=NAME, StatementId=sid, Action=action, Principal="*", **extra)
        except lam.exceptions.ResourceConflictException:
            pass
        except Exception as e:  # noqa: BLE001  (older APIs do not know InvokedViaFunctionUrl)
            print("permission", sid, "skipped:", e)

    budgets = s.client("budgets")
    budget = {"BudgetName": "myrmidon-hosted-decider", "BudgetType": "COST", "TimeUnit": "MONTHLY",
              "BudgetLimit": {"Amount": "1", "Unit": "USD"},
              "CostFilters": {"Service": ["AWS Lambda", "Amazon EC2 Container Registry (ECR)", "AWS CodeBuild",
                                          "Amazon DynamoDB", "AWS Amplify"]}}
    alerts = [{"Notification": {"NotificationType": t, "ComparisonOperator": "GREATER_THAN", "Threshold": 100,
                                "ThresholdType": "PERCENTAGE"},
               "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}]} for t in ("ACTUAL", "FORECASTED")]
    try:
        budgets.create_budget(AccountId=account, Budget=budget, NotificationsWithSubscribers=alerts)
        print("budget alert: $1/month ->", email)
    except budgets.exceptions.DuplicateRecordException:
        print("budget alert already exists")

    (ROOT / "web" / ".env.production").write_text(f"VITE_DECIDER_URL={url}\n", encoding="utf-8")
    print("Function URL:", url)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="where the $1 budget alert goes")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    main(a.email, not a.no_build)
