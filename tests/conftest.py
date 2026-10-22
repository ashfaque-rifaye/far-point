"""Shared pytest setup.

Tests never need a GPU, AWS or a camera. Anything that does carries `@pytest.mark.live`
and is skipped unless FARPOINT_LIVE=1.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keep pytest's temp dirs off C: (this laptop's convention: runtime data lives on E:).
# FARPOINT_TEST_TMP overrides; if that drive does not exist, pytest's default is used.
_tmp_root = Path(os.environ.get("FARPOINT_TEST_TMP", r"E:\farpoint-runtime\pytest-tmp"))
if _tmp_root.drive and Path(_tmp_root.drive + "\\").exists():
    _tmp_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_tmp_root))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("FARPOINT_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set FARPOINT_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    """Point FARPOINT_RUNTIME at a temp dir so no test touches E:\\farpoint-runtime itself."""
    monkeypatch.setenv("FARPOINT_RUNTIME", str(tmp_path))
    return tmp_path
