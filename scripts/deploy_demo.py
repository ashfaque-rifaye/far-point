"""Publish the dashboard's built-in demo story to AWS Amplify Hosting (us-east-1).

The real agent needs the laptop: the webcam, the local GPU for the Decider and Win32 for the screen
changes. What can live on AWS is the dashboard itself: served from any host but this machine, it
plays the scripted demo story (labelled DEMO) instead of connecting to a backend. This uploads
web/dist as a manual Amplify deployment and prints the public URL.

    npm --prefix web run build
    python scripts/deploy_demo.py
"""
import io
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
APP, BRANCH, REGION = "myrmidon-demo", "main", "us-east-1"


def zip_dist() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(DIST).as_posix())
    return buf.getvalue()


def main() -> None:
    if not (DIST / "index.html").exists():
        raise SystemExit("build the dashboard first: npm --prefix web run build")
    amp = boto3.client("amplify", region_name=REGION)
    app = next((a for a in amp.list_apps()["apps"] if a["name"] == APP), None)
    if app is None:
        app = amp.create_app(name=APP, platform="WEB",
                             description="Myrmidon dashboard, demo story (scripted numbers)")["app"]
    app_id = app["appId"]
    try:
        amp.get_branch(appId=app_id, branchName=BRANCH)
    except amp.exceptions.NotFoundException:
        amp.create_branch(appId=app_id, branchName=BRANCH, stage="PRODUCTION")
    dep = amp.create_deployment(appId=app_id, branchName=BRANCH)
    req = urllib.request.Request(dep["zipUploadUrl"], data=zip_dist(), method="PUT",
                                 headers={"Content-Type": "application/zip"})
    urllib.request.urlopen(req).read()
    amp.start_deployment(appId=app_id, branchName=BRANCH, jobId=dep["jobId"])
    while True:
        status = amp.get_job(appId=app_id, branchName=BRANCH, jobId=dep["jobId"])["job"]["summary"]["status"]
        if status in ("SUCCEED", "FAILED", "CANCELLED"):
            break
        time.sleep(5)
    print(status, f"https://{BRANCH}.{app['defaultDomain']}/")


if __name__ == "__main__":
    main()
