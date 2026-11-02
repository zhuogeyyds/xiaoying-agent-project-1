"""四个业务工具：读取素材、检查规则、查询时段、保存草稿。

明确不提供发布工具：代码层面杜绝越权发布。
工具不抛裸异常，统一返回结构化 dict，方便模型观察。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from .audit import evaluate
from .store import DataStore


def _tool_error(tool_name: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error_type": "tool_error",
        "tool": tool_name,
        "message": f"{type(exc).__name__}: {exc}",
    }


def _rule_message(result: dict[str, Any]) -> str:
    if result["passed"]:
        return "审核通过，未发现规则风险"
    if result["blocked"]:
        reasons = "；".join(
            f"{risk['rule_id']} {risk['reason']}" for risk in result["risks"]
        )
        return f"审核未通过，已阻断：{reasons}"
    reasons = "；".join(
        f"{risk['rule_id']} {risk['reason']}" for risk in result["risks"]
    )
    return f"发现需要确认的风险：{reasons}"


def build_tools(store: DataStore) -> list[Any]:
    """按给定数据仓库构建工具列表。"""

    @tool
    def read_material(material_id: str) -> dict:
        """读取指定素材的元数据。返回是否找到、素材内容、缺失字段列表。

        找不到素材时返回 found=false，不抛异常。安排排期前应先调用本工具。
        """
        try:
            return store.read_material(material_id)
        except Exception as exc:  # noqa: BLE001 - 工具统一返回结构化错误
            return _tool_error("read_material", exc)

    @tool
    def check_rules(material_id: str) -> dict:
        """检查指定素材是否通过审核规则。

        返回是否通过、风险列表（每条含规则编号、等级、原因）、是否需要补充资料。
        高风险或需要补充资料时不应保存草稿。
        """
        try:
            material = store.get_material(material_id)
            if material is None:
                return {
                    "ok": True,
                    "found": False,
                    "material_id": material_id,
                    "passed": False,
                    "blocked": False,
                    "risks": [],
                    "confirmations": [],
                    "missing_fields": [],
                    "message": f"未找到素材 {material_id}，无法检查规则",
                }
            result = evaluate(material, store.get_rules())
            result.update(
                {
                    "ok": True,
                    "found": True,
                    "material_id": material["material_id"],
                }
            )
            result["message"] = _rule_message(result)
            return result
        except Exception as exc:  # noqa: BLE001
            return _tool_error("check_rules", exc)

    @tool
    def query_slots(date: str, desired_time: str, duration_minutes: int) -> dict:
        """查询某天某时段是否可用，并给出替代时段。

        入参：日期 YYYY-MM-DD、期望时段 HH:MM、时长（分钟）。
        返回 available、冲突列表 conflicts、替代时段 alternatives。
        时段被占用时应改用 alternatives 并标记待确认，不得擅自改硬性发布时间。
        """
        try:
            return store.query_slots(date, desired_time, duration_minutes)
        except Exception as exc:  # noqa: BLE001
            return _tool_error("query_slots", exc)

    @tool
    def save_draft(
        material_id: str,
        date: str,
        time: str,
        status: str,
        pending_confirmations: list[str] | None = None,
    ) -> dict:
        """保存排期草稿（只保存草稿，不发布）。

        入参：素材编号、日期 YYYY-MM-DD、时段 HH:MM、状态、待确认项列表。
        状态只允许 draft 或 draft_pending_confirmation。
        相同素材同一天重复保存只保留一份草稿，返回已有草稿编号并标记 duplicate。
        保存失败会如实返回 ok=false 与错误类型，不得改写为成功。
        """
        try:
            return store.save_draft(
                material_id, date, time, status, pending_confirmations
            )
        except Exception as exc:  # noqa: BLE001
            return _tool_error("save_draft", exc)

    return [read_material, check_rules, query_slots, save_draft]
