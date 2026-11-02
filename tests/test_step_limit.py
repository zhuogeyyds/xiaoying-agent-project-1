"""P5：步数上限测试（真实模型，控制规模）。"""

from __future__ import annotations

from src.agent import run_case
from src.store import DataStore


def test_step_limit_returns_incomplete(data_dir) -> None:
    case = {
        "case_id": "pytest-step-limit",
        "material_id": "M01",
        "date": "2026-11-05",
        "time": "18:00",
        "hard_time": True,
        "max_steps": 4,
        "instruction": (
            "请处理素材 M01。用户要求 2026-11-05 18:00 发布，这是硬性发布时间，"
            "不得擅自更改。请完成审核与排期，只保存草稿。"
        ),
    }
    trace = run_case(
        DataStore(data_dir=data_dir),
        case,
        max_steps=4,
        write_artifacts=False,
    )

    assert trace["task_status"] == "incomplete"
    assert trace["step_limit_hit"] is True
    assert trace["runner_note"]
    assert "未完成" in trace["runner_note"]
    assert "已完成部分" in trace["runner_note"]
