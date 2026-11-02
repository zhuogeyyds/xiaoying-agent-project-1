"""P5 测试夹具：每个测试使用独立数据副本，避免相互污染。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATA_DIR  # noqa: E402
from src.store import DataStore  # noqa: E402
from src.tools import build_tools  # noqa: E402

DATA_FILES = ("materials.json", "rules.json", "schedule.json", "drafts.json")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    for filename in DATA_FILES:
        shutil.copy(DATA_DIR / filename, tmp_path / filename)
    (tmp_path / "drafts.json").write_text('{\n  "drafts": []\n}\n', encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(data_dir: Path) -> DataStore:
    return DataStore(data_dir=data_dir)


@pytest.fixture
def tools(store: DataStore):
    return build_tools(store)
