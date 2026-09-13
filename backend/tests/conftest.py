from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.runtime import Runtime, build_runtime
from backend.app.settings import load_settings


@pytest.fixture
def runtime(tmp_path) -> Runtime:
    base = load_settings()
    settings = replace(
        base,
        database_path=tmp_path / "library.db",
        artifact_root=tmp_path / "runs",
        allow_fixture_sources=True,
        worker_poll_seconds=0.01,
    )
    return build_runtime(settings)
