"""P8：离线 Mock 入口测试（不调用网络/真实模型）。"""

from __future__ import annotations

import json

from src.config import EXAMPLES_DIR
from src.mock_runner import MOCK_BOUNDARY, run_mock_case
from src.store import DataStore


def load_case(case_id: str) -> dict:
    path = EXAMPLES_DIR / "cases" / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_mock_normal_conflict(data_dir) -> None:
    trace = run_mock_case(
        DataStore(data_dir=data_dir), load_case("01-m01-normal"), write_artifacts=False
    )
    assert trace["mode"] == "mock"
    assert trace["task_status"] == "mock_draft_saved"
    assert "不证明真实模型决策" in trace["boundary"]
    assert "仅验证工具与流程" in MOCK_BOUNDARY
    assert len(trace["drafts"]) == 1
    assert trace["drafts"][0]["time"] == "19:00"
    assert trace["drafts"][0]["pending_confirmations"]
    assert "已发布" not in trace["final_output"]


def test_mock_blocked(data_dir) -> None:
    trace = run_mock_case(
        DataStore(data_dir=data_dir), load_case("02-m02-missing"), write_artifacts=False
    )
    assert trace["task_status"] == "mock_blocked"
    assert trace["drafts"] == []
    assert "不证明真实模型决策" in trace["boundary"]


def test_mock_slot_full_and_save_failure(data_dir) -> None:
    slot_case = {
        "case_id": "mock-m05-slot-full",
        "material_id": "M05",
        "date": "2026-11-06",
        "time": "18:00",
        "hard_time": True,
    }
    slot_trace = run_mock_case(
        DataStore(data_dir=data_dir), slot_case, write_artifacts=False
    )
    assert slot_trace["task_status"] == "mock_slot_conflict"
    assert slot_trace["drafts"] == []

    fail_case = {
        "case_id": "mock-save-failure",
        "material_id": "M01",
        "date": "2026-11-09",
        "time": "18:00",
        "hard_time": True,
    }
    fail_trace = run_mock_case(
        DataStore(data_dir=data_dir, fail_save=True), fail_case, write_artifacts=False
    )
    assert fail_trace["task_status"] == "mock_save_failed"
    assert fail_trace["drafts"] == []
    assert "失败" in fail_trace["final_output"]
