"""Shared pytest setup.

Tests never need a GPU, AWS or a camera. Anything that does carries `@pytest.mark.live`
and is skipped unless FARPOINT_LIVE=1.
"""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("FARPOINT_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set FARPOINT_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    """Point FARPOINT_RUNTIME at a temp dir so no test touches E:\\farpoint-runtime."""
    monkeypatch.setenv("FARPOINT_RUNTIME", str(tmp_path))
    return tmp_path
