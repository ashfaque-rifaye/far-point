"""Pre-push scan of STAGED git content. Exits 1 (and prints only file + rule, never the
match) if anything looks like a credential, the AWS account id, or image bytes.

  python scripts/prepush_scan.py
"""
from __future__ import annotations

import re
import subprocess
import sys

RULES = {
    "aws_access_key_id": re.compile(rb"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    # Patterns are split so this file does not match itself.
    "aws_secret_key_field": re.compile(rb"aws_secret" + rb"_access_key", re.I),
    "aws_session_field": re.compile(rb"aws_session" + rb"_token", re.I),
    "private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE" + rb" KEY-----"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "jpeg_bytes": re.compile(rb"\xff\xd8\xff"),
    "png_bytes": re.compile(rb"\x89PNG\r\n\x1a\n"),
    "jpeg_base64": re.compile(rb"/9j/4[A-Za-z0-9+/]{40,}"),
    "png_base64": re.compile(rb"iVBORw0KGgo[A-Za-z0-9+/]{40,}"),
}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".mp4", ".mov")


def account_id() -> bytes | None:
    try:
        import boto3
        return boto3.client("sts").get_caller_identity()["Account"].encode()
    except Exception:  # noqa: BLE001 - no creds means nothing to match
        return None


def main() -> int:
    files = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).split(b"\0")
    files = [f.decode() for f in files if f]
    acct = account_id()
    hits = []
    for f in files:
        if f.lower().endswith(IMAGE_EXT):
            hits.append((f, "image_file"))
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True).stdout
        for name, rx in RULES.items():
            if rx.search(blob):
                hits.append((f, name))
        if acct and acct in blob:
            hits.append((f, "aws_account_id"))
    print(f"scanned {len(files)} staged files; account id check {'on' if acct else 'OFF (no AWS creds)'}")
    for f, r in hits:
        print(f"HIT {r}: {f}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
