"""Shared pytest fixtures.

We redirect the SQLite archive + data/output dirs into the pytest tmp_path
before any module under test gets imported, so tests never touch the real
repo's `data/` or `output/` files.

`settings` is a frozen dataclass, so we use `object.__setattr__` to bypass
`FrozenInstanceError`. We snapshot the original values and restore them at
teardown so tests don't leak state across each other.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _force_set(obj, name, value) -> object:
    original = getattr(obj, name)
    object.__setattr__(obj, name, value)
    return original


@pytest.fixture(autouse=True)
def isolate_fs(tmp_path):
    """Redirect data_dir / output_dir / archive DB to a tmp location."""
    from config import settings
    from modules import archive

    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()

    saved = {
        "data_dir": _force_set(settings, "data_dir", data_dir),
        "output_dir": _force_set(settings, "output_dir", output_dir),
        "llm_provider": _force_set(settings, "llm_provider", "mock"),
    }
    saved_db_path = archive.DB_PATH
    archive.DB_PATH = data_dir / "archive.sqlite3"

    try:
        yield
    finally:
        for name, value in saved.items():
            object.__setattr__(settings, name, value)
        archive.DB_PATH = saved_db_path
