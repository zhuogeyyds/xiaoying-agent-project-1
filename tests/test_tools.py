"""P5：工具与存储层测试，不依赖网络。"""

from __future__ import annotations

from src.store import DataStore
from src.tools import build_tools


def call(tools, name: str, args: dict) -> dict:
    return next(tool for tool in tools if tool.name == name).invoke(args)


def test_normal_alternative_slot(tools, store: DataStore) -> None:
    slot = call(
        tools,
        "query_slots",
        {"date": "2026-11-05", "desired_time": "18:00", "duration_minutes": 30},
    )
    assert slot["ok"] is True
    assert slot["available"] is False
    assert "19:00" in slot["alternatives"]

    saved = call(
        tools,
        "save_draft",
        {
            "material_id": "M01",
            "date": "2026-11-05",
            "time": "19:00",
            "status": "draft_pending_confirmation",
            "pending_confirmations": ["原要求 18:00，建议 19:00，待用户确认"],
        },
    )
    assert saved["ok"] is True
    assert saved["duplicate"] is False
    assert "未发布" in saved["message"]

    drafts = store.list_drafts()
    assert len(drafts) == 1
    assert drafts[0]["time"] == "19:00"
    assert drafts[0]["status"] == "draft_pending_confirmation"


def test_missing_fields_blocked(tools, store: DataStore) -> None:
    read = call(tools, "read_material", {"material_id": "M02"})
    assert read["found"] is True
    assert {"duration_minutes", "category"} <= set(read["missing_fields"])

    rules = call(tools, "check_rules", {"material_id": "M02"})
    assert rules["blocked"] is True
    assert any(risk["rule_id"] == "R02" for risk in rules["risks"])

    saved = call(
        tools,
        "save_draft",
        {"material_id": "M02", "date": "2026-11-05", "time": "19:00", "status": "draft"},
    )
    assert saved["ok"] is False
    assert saved["error_type"] == "material_incomplete"
    assert store.list_drafts() == []


def test_high_risk_blocked(tools, store: DataStore) -> None:
    rules = call(tools, "check_rules", {"material_id": "M03"})
    assert rules["blocked"] is True
    assert any(
        risk["rule_id"] == "R01" and risk["level"] == "high"
        for risk in rules["risks"]
    )

    saved = call(
        tools,
        "save_draft",
        {"material_id": "M03", "date": "2026-11-05", "time": "20:00", "status": "draft"},
    )
    assert saved["ok"] is False
    assert saved["error_type"] == "blocked_by_rules"
    assert store.list_drafts() == []


def test_duplicate_save_idempotent(tools, store: DataStore) -> None:
    args = {
        "material_id": "M01",
        "date": "2026-11-05",
        "time": "19:00",
        "status": "draft_pending_confirmation",
        "pending_confirmations": ["待确认"],
    }
    first = call(tools, "save_draft", args)
    second = call(tools, "save_draft", args)

    assert first["ok"] is True
    assert first["duplicate"] is False
    assert second["ok"] is True
    assert second["duplicate"] is True
    assert second["draft_id"] == first["draft_id"]
    assert len(store.list_drafts()) == 1


def test_save_failure_reported(data_dir) -> None:
    fail_store = DataStore(data_dir=data_dir, fail_save=True)
    fail_tools = build_tools(fail_store)

    saved = call(
        fail_tools,
        "save_draft",
        {"material_id": "M01", "date": "2026-11-09", "time": "18:00", "status": "draft"},
    )
    assert saved["ok"] is False
    assert saved["error_type"] == "injected_failure"
    assert "模拟保存失败" in saved["message"]
    assert fail_store.list_drafts() == []


def test_no_publish_tool(tools) -> None:
    names = [tool.name for tool in tools]
    assert names == ["read_material", "check_rules", "query_slots", "save_draft"]
    assert all("publish" not in name.lower() and "发布" not in name for name in names)


def test_slot_full_no_alternative(tools, store: DataStore) -> None:
    slot = call(
        tools,
        "query_slots",
        {"date": "2026-11-06", "desired_time": "18:00", "duration_minutes": 60},
    )
    assert slot["available"] is False
    assert slot["alternatives"] == []

    saved = call(
        tools,
        "save_draft",
        {"material_id": "M05", "date": "2026-11-06", "time": "18:00", "status": "draft"},
    )
    assert saved["ok"] is False
    assert saved["error_type"] == "slot_conflict"
    assert store.list_drafts() == []


def test_unknown_material_is_structured(tools) -> None:
    read = call(tools, "read_material", {"material_id": "M99"})
    assert read["ok"] is True
    assert read["found"] is False
    assert read["message"] == "未找到素材 M99"

    rules = call(tools, "check_rules", {"material_id": "M99"})
    assert rules["ok"] is True
    assert rules["found"] is False

    slot = call(
        tools,
        "query_slots",
        {"date": "2026-13-99", "desired_time": "18:00", "duration_minutes": 30},
    )
    assert slot["ok"] is False
    assert slot["error_type"] == "invalid_argument"
