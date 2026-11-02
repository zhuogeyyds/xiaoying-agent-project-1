"""本地 JSON 数据访问、草稿幂等、时段冲突校验与保存失败注入。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit import evaluate, missing_fields
from .config import DATA_DIR

ALLOWED_DRAFT_STATUSES = {"draft", "draft_pending_confirmation"}
DAY_START_MINUTES = 9 * 60
DAY_END_MINUTES = 21 * 60
SLOT_STEP_MINUTES = 60


def _to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _normalize_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")


def _normalize_time(value: str) -> str:
    return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


class DataStore:
    """所有读写都走这里；工具层只做薄封装。"""

    def __init__(self, data_dir: str | Path | None = None, fail_save: bool = False):
        self.data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
        self.fail_save = fail_save

    # ---------- 基础读写 ----------

    def _read_list(self, filename: str, key: str) -> list[dict[str, Any]]:
        path = self.data_dir / filename
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        items = data.get(key, [])
        if not isinstance(items, list):
            raise ValueError(f"{filename} 中的 {key} 不是列表")
        return items

    def _write_list(self, filename: str, key: str, items: list[dict[str, Any]]) -> None:
        path = self.data_dir / filename
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps({key: items}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)

    def get_material(self, material_id: str) -> dict[str, Any] | None:
        target = (material_id or "").strip()
        for material in self._read_list("materials.json", "materials"):
            if material.get("material_id") == target:
                return material
        return None

    def get_rules(self) -> list[dict[str, Any]]:
        return self._read_list("rules.json", "rules")

    def get_schedule(self, date: str | None = None) -> list[dict[str, Any]]:
        entries = self._read_list("schedule.json", "schedule")
        if date is None:
            return entries
        return [entry for entry in entries if entry.get("date") == date]

    def list_drafts(self) -> list[dict[str, Any]]:
        return self._read_list("drafts.json", "drafts")

    # ---------- 工具一：读取素材 ----------

    def read_material(self, material_id: str) -> dict[str, Any]:
        material = self.get_material(material_id)
        if material is None:
            return {
                "ok": True,
                "found": False,
                "material": None,
                "missing_fields": [],
                "message": f"未找到素材 {material_id}",
            }
        missing = missing_fields(material)
        message = f"已找到素材 {material['material_id']}"
        if missing:
            message += f"，缺少字段：{'、'.join(missing)}"
        return {
            "ok": True,
            "found": True,
            "material": material,
            "missing_fields": missing,
            "message": message,
        }

    # ---------- 工具三：查询时段 ----------

    def _occupied_intervals(self, date: str) -> list[tuple[int, int, dict[str, Any]]]:
        intervals: list[tuple[int, int, dict[str, Any]]] = []
        for entry in self.get_schedule(date):
            try:
                start = _to_minutes(str(entry.get("time", "")))
                duration = int(entry.get("duration_minutes", 0))
            except (TypeError, ValueError):
                continue
            if duration > 0:
                intervals.append((start, start + duration, entry))
        return intervals

    @staticmethod
    def _overlaps(
        start: int, end: int, intervals: list[tuple[int, int, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        return [
            entry
            for occupied_start, occupied_end, entry in intervals
            if start < occupied_end and end > occupied_start
        ]

    def _fits(
        self, start: int, duration: int, intervals: list[tuple[int, int, dict[str, Any]]]
    ) -> bool:
        end = start + duration
        if start < DAY_START_MINUTES or end > DAY_END_MINUTES:
            return False
        return not self._overlaps(start, end, intervals)

    def _alternatives(
        self,
        desired_start: int,
        duration: int,
        intervals: list[tuple[int, int, dict[str, Any]]],
    ) -> list[str]:
        free = [
            start
            for start in range(DAY_START_MINUTES, DAY_END_MINUTES, SLOT_STEP_MINUTES)
            if start != desired_start and self._fits(start, duration, intervals)
        ]
        after = [start for start in free if start > desired_start]
        before = [start for start in free if start < desired_start][::-1]
        return [_to_hhmm(start) for start in (after + before)[:3]]

    def query_slots(
        self, date: str, desired_time: str, duration_minutes: int
    ) -> dict[str, Any]:
        try:
            normalized_date = _normalize_date(date)
            normalized_time = _normalize_time(desired_time)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_type": "invalid_argument",
                "message": f"日期或时段格式不正确：date={date!r}, time={desired_time!r}",
            }
        try:
            duration = int(duration_minutes)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_type": "invalid_argument",
                "message": f"时长必须是正整数：{duration_minutes!r}",
            }
        if isinstance(duration_minutes, bool) or duration <= 0:
            return {
                "ok": False,
                "error_type": "invalid_argument",
                "message": f"时长必须是正整数：{duration_minutes!r}",
            }

        intervals = self._occupied_intervals(normalized_date)
        start = _to_minutes(normalized_time)
        end = start + duration
        conflicts = self._overlaps(start, end, intervals)
        available = self._fits(start, duration, intervals)
        alternatives = self._alternatives(start, duration, intervals)

        conflict_view = [
            {
                "time": entry.get("time"),
                "material_id": entry.get("material_id"),
                "title": entry.get("title"),
                "duration_minutes": entry.get("duration_minutes"),
            }
            for entry in conflicts
        ]
        if available:
            message = "时段可用"
        elif alternatives:
            message = f"时段已占用，建议替代时段：{'、'.join(alternatives)}；需用户确认"
        else:
            message = "时段已占用，当天没有可用替代时段"

        return {
            "ok": True,
            "date": normalized_date,
            "desired_time": normalized_time,
            "duration_minutes": duration,
            "available": available,
            "conflicts": conflict_view,
            "alternatives": alternatives,
            "message": message,
        }

    # ---------- 工具四：保存草稿 ----------

    def save_draft(
        self,
        material_id: str,
        date: str,
        time: str,
        status: str,
        pending_confirmations: Any = None,
    ) -> dict[str, Any]:
        material = self.get_material(material_id)
        if material is None:
            return {
                "ok": False,
                "error_type": "material_not_found",
                "message": f"未找到素材 {material_id}，不能保存草稿",
            }

        normalized_status = (status or "").strip()
        if normalized_status not in ALLOWED_DRAFT_STATUSES:
            return {
                "ok": False,
                "error_type": "invalid_status",
                "message": (
                    f"状态 {status!r} 不允许保存。只允许草稿状态："
                    f"{'、'.join(sorted(ALLOWED_DRAFT_STATUSES))}；不提供发布。"
                ),
            }

        try:
            normalized_date = _normalize_date(date)
            normalized_time = _normalize_time(time)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_type": "invalid_argument",
                "message": f"日期或时段格式不正确：date={date!r}, time={time!r}",
            }

        drafts = self.list_drafts()
        idempotency_key = f"{material['material_id']}:{normalized_date}"
        for draft in drafts:
            if draft.get("idempotency_key") == idempotency_key:
                return {
                    "ok": True,
                    "draft_id": draft.get("draft_id"),
                    "duplicate": True,
                    "status": draft.get("status"),
                    "message": (
                        f"相同素材同一天已有草稿 {draft.get('draft_id')}，"
                        "未新增第二份"
                    ),
                }

        missing = missing_fields(material)
        if missing:
            return {
                "ok": False,
                "error_type": "material_incomplete",
                "message": f"素材缺少字段：{'、'.join(missing)}，不能保存草稿",
                "missing_fields": missing,
            }

        audit = evaluate(material, self.get_rules())
        if audit["blocked"]:
            reasons = "；".join(
                f"{risk['rule_id']} {risk['reason']}" for risk in audit["risks"]
            )
            return {
                "ok": False,
                "error_type": "blocked_by_rules",
                "message": f"规则审核未通过，不能保存草稿：{reasons}",
                "risks": audit["risks"],
            }

        try:
            duration = int(material.get("duration_minutes"))
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error_type": "material_incomplete",
                "message": "素材时长无效，不能保存草稿",
            }
        if duration <= 0:
            return {
                "ok": False,
                "error_type": "material_incomplete",
                "message": "素材时长必须为正整数，不能保存草稿",
            }

        intervals = self._occupied_intervals(normalized_date)
        start = _to_minutes(normalized_time)
        conflicts = self._overlaps(start, start + duration, intervals)
        if conflicts:
            alternatives = self._alternatives(start, duration, intervals)
            return {
                "ok": False,
                "error_type": "slot_conflict",
                "message": (
                    "目标时段与已有排期冲突，未保存；请改用替代时段并标记待确认。"
                    f"替代时段：{'、'.join(alternatives) if alternatives else '无'}"
                ),
                "conflicts": [
                    {"time": entry.get("time"), "material_id": entry.get("material_id")}
                    for entry in conflicts
                ],
                "alternatives": alternatives,
            }

        if self.fail_save:
            return {
                "ok": False,
                "error_type": "injected_failure",
                "message": "模拟保存失败：草稿写入被拒绝（故障注入），未产生草稿",
            }

        existing_ids = [str(draft.get("draft_id", "")) for draft in drafts]
        numbers = [
            int(item[1:])
            for item in existing_ids
            if item.startswith("D") and item[1:].isdigit()
        ]
        draft_id = f"D{max(numbers, default=0) + 1:03d}"
        draft = {
            "draft_id": draft_id,
            "material_id": material["material_id"],
            "date": normalized_date,
            "time": normalized_time,
            "status": normalized_status,
            "pending_confirmations": _as_list(pending_confirmations),
            "idempotency_key": idempotency_key,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        drafts.append(draft)
        try:
            self._write_list("drafts.json", "drafts", drafts)
        except OSError as exc:
            return {
                "ok": False,
                "error_type": "io_error",
                "message": f"草稿写入失败：{type(exc).__name__}: {exc}",
            }
        return {
            "ok": True,
            "draft_id": draft_id,
            "duplicate": False,
            "status": normalized_status,
            "pending_confirmations": draft["pending_confirmations"],
            "message": f"草稿 {draft_id} 已保存（仅草稿，未发布）",
        }
