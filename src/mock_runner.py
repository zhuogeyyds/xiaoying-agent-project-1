"""显式离线 Mock 入口：仅验证工具与流程，不证明真实模型决策。

设计边界：
- 只有 CLI 显式传 ``--offline-mock`` 才会进入本模块；
- 不调用真实模型，也不进入 ReAct Agent；
- 用真实的 DataStore 和四个工具，按固定脚本演示流程；
- trace/output 明确标记 ``mode="mock"`` 与边界说明；
- 真实模式缺少密钥时仍然明确报错，不会自动落到这里。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .agent import summarize_tool_result
from .config import OUTPUTS_DIR, TRACES_DIR
from .store import DataStore
from .tools import build_tools

MOCK_BOUNDARY = (
    "仅验证工具与流程，不证明真实模型决策效果；"
    "真实模式仍使用 ReAct Agent，模型不可用时明确报错，不自动降级。"
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_mock_case(
    store: DataStore,
    case: dict[str, Any],
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """按固定脚本跑一个用例，返回 trace 结构。"""
    tools = build_tools(store)
    events: list[dict[str, Any]] = []

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = next(item for item in tools if item.name == name)
        result = tool.invoke(args)
        events.append(
            {
                "step": len(events) + 1,
                "type": "tool",
                "tool": name,
                "args": args,
                "result": result,
                "summary": summarize_tool_result(name, result),
            }
        )
        return result

    case_id = case["case_id"]
    material_id = case["material_id"]
    date = case["date"]
    requested_time = case["time"]

    read = call("read_material", {"material_id": material_id})
    if not read.get("found"):
        return _finalize(
            store, case, events, "mock_not_found", f"未找到素材 {material_id}，Mock 流程结束。", write_artifacts
        )

    check = call("check_rules", {"material_id": material_id})
    if not check.get("found"):
        return _finalize(
            store, case, events, "mock_blocked", f"素材 {material_id} 无法检查规则，Mock 阻断。", write_artifacts
        )
    if check.get("blocked"):
        risks = "；".join(
            f"{risk.get('rule_id')} {risk.get('reason')}" for risk in check.get("risks", [])
        )
        return _finalize(
            store, case, events, "mock_blocked", f"规则未通过，Mock 阻断：{risks}", write_artifacts
        )

    duration = read.get("material", {}).get("duration_minutes") or 30
    slot = call(
        "query_slots",
        {"date": date, "desired_time": requested_time, "duration_minutes": duration},
    )

    chosen_time = requested_time
    pending: list[str] = []
    if not slot.get("available"):
        alternatives = slot.get("alternatives") or []
        if not alternatives:
            return _finalize(
                store,
                case,
                events,
                "mock_slot_conflict",
                f"{date} {requested_time} 被占用且没有替代时段，Mock 不保存草稿。",
                write_artifacts,
            )
        chosen_time = alternatives[0]
        pending = [
            f"原要求 {date} {requested_time} 已被占用",
            f"Mock 按脚本选择替代时段 {chosen_time}",
            "替代时段需用户确认",
        ]

    save = call(
        "save_draft",
        {
            "material_id": material_id,
            "date": date,
            "time": chosen_time,
            "status": "draft_pending_confirmation" if pending else "draft",
            "pending_confirmations": pending,
        },
    )

    if save.get("ok") and save.get("duplicate"):
        status = "mock_duplicate"
        message = f"相同素材同一天已有草稿 {save.get('draft_id')}，Mock 未新增。"
    elif save.get("ok"):
        status = "mock_draft_saved"
        message = f"Mock 已保存草稿 {save.get('draft_id')}（{chosen_time}，仅草稿）。"
    elif save.get("error_type") in {"injected_failure", "io_error"}:
        status = "mock_save_failed"
        message = f"Mock 保存失败：{save.get('message')}"
    elif save.get("error_type") == "slot_conflict":
        status = "mock_slot_conflict"
        message = f"Mock 遇到时段冲突：{save.get('message')}"
    else:
        status = "mock_blocked"
        message = f"Mock 保存未通过：{save.get('message')}"

    return _finalize(store, case, events, status, message, write_artifacts)


def _finalize(
    store: DataStore,
    case: dict[str, Any],
    events: list[dict[str, Any]],
    status: str,
    message: str,
    write_artifacts: bool,
) -> dict[str, Any]:
    saved_ids = {
        event["result"].get("draft_id")
        for event in events
        if event["type"] == "tool"
        and event.get("tool") == "save_draft"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
        and event["result"].get("draft_id")
    }
    drafts = [draft for draft in store.list_drafts() if draft.get("draft_id") in saved_ids]
    final_output = (
        f"[MOCK] 仅验证流程，不证明真实模型决策效果。\n"
        f"素材 {case['material_id']}：{message}"
    )
    trace = {
        "run_id": f"mock-{case['case_id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "case_id": case["case_id"],
        "mode": "mock",
        "boundary": MOCK_BOUNDARY,
        "model": None,
        "temperature": None,
        "created_at": _now(),
        "events": events,
        "task_status": status,
        "drafts": drafts,
        "final_output": final_output,
    }

    if write_artifacts:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        trace_path = TRACES_DIR / f"mock-{case['case_id']}.json"
        output_path = OUTPUTS_DIR / f"mock-{case['case_id']}.json"
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        output_path.write_text(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "mode": "mock",
                    "boundary": MOCK_BOUNDARY,
                    "task_status": status,
                    "final_output": final_output,
                    "drafts": drafts,
                    "trace": trace_path.relative_to(TRACES_DIR.parent.parent).as_posix(),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        trace["trace_path"] = trace_path
        trace["output_path"] = output_path
    else:
        trace["trace_path"] = None
        trace["output_path"] = None
    return trace
