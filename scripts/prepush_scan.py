"""Pre-push scan. Exits 1 (and prints only file + rule, never the match) if anything looks
like a credential, the AWS account id, or image bytes.

  python scripts/prepush_scan.py                       # STAGED content (git diff --cached)
  python scripts/prepush_scan.py --range origin/main..HEAD   # every file the push would change

Dashboard screenshots under docs/images/ (names starting with "dashboard-") and the three rendered
doc images (architecture, decision-loop, cover) are the only images allowed; the UI never shows camera frames, and every other image is refused.
"""
from __future__ import annotations

import argparse
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
IMAGE_RULES = {"jpeg_bytes", "png_bytes"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".mp4", ".mov")
SCREENSHOT_PREFIX = "docs/images/dashboard-"
# Rendered diagrams and the article cover (from SVG/HTML sources next to them, scripts/render_doc_images.py).
DOC_IMAGES = {"docs/images/architecture.png", "docs/images/decision-loop.png", "docs/images/cover.png"}


def account_id() -> bytes | None:
    try:
        import boto3
        return boto3.client("sts").get_caller_identity()["Account"].encode()
    except Exception:  # noqa: BLE001 - no creds means nothing to match
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", help="scan files changed in this commit range (blobs at the range end)")
    a = ap.parse_args(argv)
    if a.range:
        out = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=d", "-z", a.range])
        ref = a.range.split("..")[-1] or "HEAD"
        show = lambda f: subprocess.run(["git", "show", f"{ref}:{f}"], capture_output=True).stdout  # noqa: E731
    else:
        out = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=d", "-z"])
        show = lambda f: subprocess.run(["git", "show", f":{f}"], capture_output=True).stdout  # noqa: E731
    files = [f.decode() for f in out.split(b"\0") if f]
    acct = account_id()
    hits = []
    for f in files:
        screenshot = (f.startswith(SCREENSHOT_PREFIX) and f.lower().endswith(".png")) or f in DOC_IMAGES
        if f.lower().endswith(IMAGE_EXT) and not screenshot:
            hits.append((f, "image_file"))
        blob = show(f)
        for name, rx in RULES.items():
            if screenshot and name in IMAGE_RULES:
                continue
            if rx.search(blob):
                hits.append((f, name))
        if acct and acct in blob:
            hits.append((f, "aws_account_id"))
    scope = a.range or "staged"
    print(f"scanned {len(files)} files ({scope}); account id check {'on' if acct else 'OFF (no AWS creds)'}")
    for f, r in hits:
        print(f"HIT {r}: {f}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
