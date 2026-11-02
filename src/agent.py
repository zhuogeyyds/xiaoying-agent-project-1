"""LangGraph 预构建 ReAct Agent：系统提示词、业务状态、步数上限与运行记录。"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState

from .config import MODEL_NAME, MODEL_TEMPERATURE, OUTPUTS_DIR, TRACES_DIR
from .llm import create_chat_model, extract_text
from .store import DataStore
from .tools import build_tools

DEFAULT_MAX_STEPS = 16
STEP_GUARD_MARKER = "【步数提醒】"

SYSTEM_PROMPT = """你是内容团队的「素材审核与发布排期 Agent」。你的职责是审核素材、发现风险与时段冲突，并且只保存排期草稿。

【六条红线】
1. 只能保存草稿；绝不能声称内容已经上线，最终输出不得包含表示“发布完成”的字样。
2. 用户给出的硬性发布时间不得擅自更改。目标时段被占用时，只能建议替代时段，并把改动标记为待确认，等待用户确认。
3. 素材关键字段缺失、规则审核为高风险、或规则要求补充资料时，必须阻断，不保存草稿。
4. 保存失败必须如实返回失败，不得改写成成功。
5. 相同素材同一天重复保存只保留一份草稿；重复提交时返回已有草稿编号，不新增。
6. 剩余步数不足时，立即停止调用工具，返回“未完成”状态，并说明已完成部分。

【可用工具】
- read_material(material_id)：读取素材，返回素材内容与缺失字段。
- check_rules(material_id)：返回是否通过、风险列表（规则编号/等级/原因）、是否需要补充资料。
- query_slots(date, desired_time, duration_minutes)：返回时段是否可用、冲突列表、替代时段。
- save_draft(material_id, date, time, status, pending_confirmations)：只保存草稿；status 用 draft 或 draft_pending_confirmation。

【工作方式】
- 没有固定步骤顺序，根据上一步工具结果决定下一步。
- 调用工具前，用一句话说明你为什么要做这个动作；这句话会写入运行记录。
- 先了解素材和规则，再决定是否排期；需要排期时先查时段。
- 硬性时段被占用时，不要改硬性要求，改为建议一个可用替代时段，并在草稿待确认项中写明原要求、建议时段与“待用户确认”。
- 保存草稿时必须使用可用时段：原硬性时段被占用时，草稿时间用替代时段（例如 19:00），原要求只写入待确认项；不要把草稿保存到已占用时段。
- 如果 save_draft 返回 slot_conflict，读取 alternatives，改用替代时段重试一次，不要反复提交同一冲突时段。
- 只有规则通过且时段可用（或替代时段已标记待确认）时才保存草稿。
- 素材缺关键字段、命中高风险规则、或没有可用替代时段时，明确说明阻断原因，不保存。
- 结束时输出结构化摘要：素材编号、审核状态、风险原因、建议时段、待确认项、草稿保存状态。
- 不要输出内部思维过程。"""


class SchedulingState(AgentState):
    """在 AgentState 上追加业务状态；messages 与 remaining_steps 由框架维护。"""

    task_status: str
    drafts: list[dict[str, Any]]
    pending_confirmations: list[str]


def _make_step_guard(step_state: dict[str, Any]):
    """生成步数守卫，并把每次模型调用时的剩余步数记录到 step_state。"""

    def step_guard(state: SchedulingState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        remaining = state.get("remaining_steps")
        step_state["last_remaining"] = remaining
        if isinstance(remaining, int) and remaining <= 3:
            step_state["reminded"] = True
            reminder = HumanMessage(
                content=(
                    f"{STEP_GUARD_MARKER}剩余步数不足（约 {remaining} 步）。"
                    "请立即停止调用工具，基于已完成的工具结果输出最终结论，"
                    "明确写出“未完成”以及已完成部分和缺口。不要再调用任何工具。"
                )
            )
            return {"llm_input_messages": [*messages, reminder]}
        return {"llm_input_messages": messages}

    return step_guard


def build_agent(store: DataStore, step_state: dict[str, Any] | None = None):
    """组装预构建 ReAct Agent。"""
    model = create_chat_model()
    tools = build_tools(store)
    recorder = {} if step_state is None else step_state
    return create_react_agent(
        model,
        tools,
        prompt=SYSTEM_PROMPT,
        state_schema=SchedulingState,
        pre_model_hook=_make_step_guard(recorder),
    )


def build_case_prompt(case: dict[str, Any]) -> str:
    hard = "是" if case.get("hard_time", True) else "否"
    instruction = case.get("instruction", "").strip()
    return (
        f"{instruction}\n\n"
        f"素材编号：{case['material_id']}\n"
        f"用户要求发布时间：{case['date']} {case['time']}\n"
        f"是否硬性发布时间：{hard}\n"
        "请只处理该素材。"
    )


def _parse_tool_content(content: Any) -> Any:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}
    return content


def summarize_tool_result(tool: str, result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)[:300]
    if tool == "read_material":
        if not result.get("found"):
            return f"未找到素材：{result.get('message', '')}"
        missing = result.get("missing_fields") or []
        return f"找到素材；缺失字段={missing or '无'}"
    if tool == "check_rules":
        if not result.get("found"):
            return "未找到素材，无法检查规则"
        risks = result.get("risks") or []
        rule_ids = [risk.get("rule_id") for risk in risks]
        return (
            f"passed={result.get('passed')} blocked={result.get('blocked')} "
            f"needs_supplement={result.get('needs_supplement')} rules={rule_ids}"
        )
    if tool == "query_slots":
        return (
            f"available={result.get('available')} "
            f"conflicts={len(result.get('conflicts') or [])} "
            f"alternatives={result.get('alternatives')}"
        )
    if tool == "save_draft":
        return (
            f"ok={result.get('ok')} draft_id={result.get('draft_id')} "
            f"duplicate={result.get('duplicate')} error_type={result.get('error_type')}"
        )
    return str(result)[:300]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_case(
    store: DataStore,
    case: dict[str, Any],
    max_steps: int | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """真实运行一个用例，流式收集事件并写入 trace / output。"""
    case_id = case["case_id"]
    limit = int(max_steps or case.get("max_steps") or DEFAULT_MAX_STEPS)
    prompt = build_case_prompt(case)
    step_state: dict[str, Any] = {}
    agent = build_agent(store, step_state=step_state)

    events: list[dict[str, Any]] = []
    pending_calls: dict[str, dict[str, Any]] = {}
    executed_calls: set[str] = set()
    all_messages: list[Any] = []
    last_remaining: int | None = None
    step_limit_hit = False
    error: str | None = None
    started = time.perf_counter()

    initial_state = {
        "messages": [HumanMessage(content=prompt)],
        "task_status": "in_progress",
        "drafts": [],
        "pending_confirmations": [],
    }

    try:
        for chunk in agent.stream(
            initial_state,
            config={"recursion_limit": limit},
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                if node not in {"agent", "tools"} or not isinstance(update, dict):
                    continue
                if isinstance(update.get("remaining_steps"), int):
                    last_remaining = update["remaining_steps"]
                for message in update.get("messages") or []:
                    all_messages.append(message)
                    if isinstance(message, AIMessage):
                        calls = list(message.tool_calls or [])
                        content = extract_text(message).strip()
                        events.append(
                            {
                                "step": len(events) + 1,
                                "type": "model",
                                "node": node,
                                "content": content,
                                "tool_calls": [
                                    {
                                        "id": call.get("id"),
                                        "name": call.get("name"),
                                        "args": call.get("args"),
                                    }
                                    for call in calls
                                ],
                            }
                        )
                        for call in calls:
                            pending_calls[call.get("id", "")] = {
                                "name": call.get("name"),
                                "args": call.get("args"),
                            }
                    elif isinstance(message, ToolMessage):
                        call = pending_calls.get(message.tool_call_id, {})
                        executed_calls.add(message.tool_call_id or "")
                        result = _parse_tool_content(message.content)
                        tool_name = message.name or call.get("name")
                        events.append(
                            {
                                "step": len(events) + 1,
                                "type": "tool",
                                "node": node,
                                "tool": tool_name,
                                "args": call.get("args"),
                                "result": result,
                                "summary": summarize_tool_result(str(tool_name), result),
                            }
                        )
    except GraphRecursionError as exc:
        step_limit_hit = True
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - 运行失败必须如实暴露
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    if isinstance(step_state.get("last_remaining"), int):
        last_remaining = step_state["last_remaining"]

    final_ai = [
        message
        for message in all_messages
        if isinstance(message, AIMessage) and not (message.tool_calls or [])
    ]
    final_output = extract_text(final_ai[-1]).strip() if final_ai else ""

    unresolved_calls = {
        call_id: call
        for call_id, call in pending_calls.items()
        if call_id not in executed_calls
    }
    if unresolved_calls:
        step_limit_hit = True
    if isinstance(last_remaining, int) and last_remaining < 2:
        step_limit_hit = True
    if "need more steps" in final_output.lower():
        step_limit_hit = True
    if any(
        "步数提醒" in str(event.get("content") or "")
        or "步数上限" in str(event.get("content") or "")
        for event in events
        if event["type"] == "model"
    ):
        step_limit_hit = True
    if not final_output and step_limit_hit:
        final_output = "未完成：达到步数上限，模型未返回最终结论。"

    saved_draft_ids = {
        event["result"].get("draft_id")
        for event in events
        if event["type"] == "tool"
        and event.get("tool") == "save_draft"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is True
        and event["result"].get("draft_id")
    }
    drafts = [
        draft
        for draft in store.list_drafts()
        if draft.get("draft_id") in saved_draft_ids
    ]
    pending_confirmations = [
        item for draft in drafts for item in draft.get("pending_confirmations", [])
    ]

    blocked_observed = any(
        event["type"] == "tool"
        and event.get("tool") == "check_rules"
        and isinstance(event.get("result"), dict)
        and event["result"].get("blocked") is True
        for event in events
    )
    save_failure_observed = any(
        event["type"] == "tool"
        and event.get("tool") == "save_draft"
        and isinstance(event.get("result"), dict)
        and event["result"].get("ok") is False
        and event["result"].get("error_type") in {"injected_failure", "io_error"}
        for event in events
    )
    slot_full_observed = any(
        event["type"] == "tool"
        and event.get("tool") == "query_slots"
        and isinstance(event.get("result"), dict)
        and event["result"].get("available") is False
        and event["result"].get("alternatives") == []
        for event in events
    )

    if (
        step_state.get("reminded")
        and not saved_draft_ids
        and not blocked_observed
        and not save_failure_observed
        and not slot_full_observed
    ):
        # 步数守卫已提醒，但没有完成保存/阻断/失败上报，视为未完成。
        step_limit_hit = True

    if error and not step_limit_hit:
        task_status = "error"
    elif step_limit_hit or (isinstance(last_remaining, int) and last_remaining < 2):
        task_status = "incomplete"
    elif drafts:
        task_status = "draft_saved"
    elif save_failure_observed:
        task_status = "save_failed"
    elif blocked_observed:
        task_status = "blocked"
    elif slot_full_observed:
        task_status = "slot_conflict"
    else:
        task_status = "no_draft"

    runner_note = None
    if step_limit_hit:
        completed_tools = [str(event.get("tool")) for event in events if event["type"] == "tool"]
        runner_note = (
            f"未完成：达到步数上限（max_steps={limit}）。"
            f"已完成部分：{'、'.join(completed_tools) if completed_tools else '无工具调用完成'}；"
            f"未执行的工具调用：{len(unresolved_calls)} 个。"
        )

    red_line_ok = "已发布" not in final_output and not any(
        "已发布" in str(event.get("content") or "")
        for event in events
        if event["type"] == "model"
    )

    trace = {
        "run_id": f"{case_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "case_id": case_id,
        "model": MODEL_NAME,
        "temperature": MODEL_TEMPERATURE,
        "max_steps": limit,
        "started_at": _now(),
        "elapsed_ms": elapsed_ms,
        "input": prompt,
        "events": events,
        "final_output": final_output,
        "task_status": task_status,
        "drafts": drafts,
        "pending_confirmations": pending_confirmations,
        "step_limit_hit": step_limit_hit,
        "remaining_steps": last_remaining,
        "unresolved_tool_calls": len(unresolved_calls),
        "save_failure_observed": save_failure_observed,
        "slot_full_observed": slot_full_observed,
        "runner_note": runner_note,
        "red_line_ok": red_line_ok,
        "error": error,
    }

    if write_artifacts:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        trace_path = TRACES_DIR / f"{case_id}.json"
        output_path = OUTPUTS_DIR / f"{case_id}.json"
        trace_path.write_text(
            json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        output = {
            "case_id": case_id,
            "task_status": task_status,
            "final_output": final_output,
            "drafts": drafts,
            "pending_confirmations": pending_confirmations,
            "step_limit_hit": step_limit_hit,
            "runner_note": runner_note,
            "trace": trace_path.relative_to(TRACES_DIR.parent.parent).as_posix(),
        }
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        trace["trace_path"] = trace_path
        trace["output_path"] = output_path
    else:
        trace["trace_path"] = None
        trace["output_path"] = None
    return trace
