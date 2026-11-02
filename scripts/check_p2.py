"""P2 自测：合成数据、四个工具、幂等、保存失败注入、无发布工具。

在临时目录中运行，不污染 data/drafts.json。
真实运行输出写入 examples/traces/01-p2-tools.json。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DATA_DIR, TRACES_DIR  # noqa: E402
from src.store import DataStore  # noqa: E402
from src.tools import build_tools  # noqa: E402

CHECKS: list[dict] = []
SAMPLES: dict = {}


def check(name: str, condition: bool, detail: str) -> None:
    CHECKS.append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}: {detail}")


def call(tools, name: str, args: dict) -> dict:
    return next(tool for tool in tools if tool.name == name).invoke(args)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with tempfile.TemporaryDirectory() as temp:
        data_dir = Path(temp)
        for filename in ("materials.json", "rules.json", "schedule.json", "drafts.json"):
            shutil.copy(DATA_DIR / filename, data_dir / filename)

        store = DataStore(data_dir=data_dir)
        tools = build_tools(store)
        names = [tool.name for tool in tools]

        materials = json.loads((data_dir / "materials.json").read_text(encoding="utf-8"))["materials"]
        rules = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))["rules"]
        schedule = json.loads((data_dir / "schedule.json").read_text(encoding="utf-8"))["schedule"]

        check("数据-素材数量", len(materials) == 6, f"materials={len(materials)}")
        check("数据-规则数量", len(rules) == 5, f"rules={len(rules)}")
        check("数据-排期条目", len(schedule) == 13, f"schedule={len(schedule)}")
        check("数据-草稿初始为空", len(store.list_drafts()) == 0, f"drafts={len(store.list_drafts())}")
        check("工具-恰好四个", names == ["read_material", "check_rules", "query_slots", "save_draft"], f"tools={names}")
        check(
            "工具-没有发布工具",
            all("publish" not in name.lower() and "发布" not in name for name in names),
            f"tools={names}",
        )

        read_m01 = call(tools, "read_material", {"material_id": "M01"})
        SAMPLES["read_m01"] = read_m01
        check("读取-M01 完整", read_m01.get("found") is True and read_m01.get("missing_fields") == [], read_m01.get("message", ""))

        read_m02 = call(tools, "read_material", {"material_id": "M02"})
        SAMPLES["read_m02"] = read_m02
        missing = set(read_m02.get("missing_fields", []))
        check(
            "读取-M02 缺字段",
            read_m02.get("found") is True and {"duration_minutes", "category"} <= missing,
            f"missing={sorted(missing)}",
        )

        read_missing = call(tools, "read_material", {"material_id": "M99"})
        check("读取-不存在不抛异常", read_missing.get("found") is False, read_missing.get("message", ""))

        rule_m01 = call(tools, "check_rules", {"material_id": "M01"})
        SAMPLES["check_m01"] = rule_m01
        check("规则-M01 通过", rule_m01.get("passed") is True and rule_m01.get("blocked") is False, rule_m01.get("message", ""))

        rule_m02 = call(tools, "check_rules", {"material_id": "M02"})
        SAMPLES["check_m02"] = rule_m02
        check(
            "规则-M02 缺字段阻断",
            rule_m02.get("blocked") is True and any(risk.get("rule_id") == "R02" for risk in rule_m02.get("risks", [])),
            rule_m02.get("message", ""),
        )

        rule_m03 = call(tools, "check_rules", {"material_id": "M03"})
        SAMPLES["check_m03"] = rule_m03
        check(
            "规则-M03 医疗高风险阻断",
            rule_m03.get("blocked") is True and any(risk.get("rule_id") == "R01" and risk.get("level") == "high" for risk in rule_m03.get("risks", [])),
            rule_m03.get("message", ""),
        )

        rule_m04 = call(tools, "check_rules", {"material_id": "M04"})
        check(
            "规则-M04 风险独立于时段",
            rule_m04.get("blocked") is True and any(risk.get("rule_id") == "R01" for risk in rule_m04.get("risks", [])),
            rule_m04.get("message", ""),
        )

        rule_m06 = call(tools, "check_rules", {"material_id": "M06"})
        SAMPLES["check_m06"] = rule_m06
        check(
            "规则-M06 缺授权需补充",
            rule_m06.get("needs_supplement") is True and any(risk.get("rule_id") == "R04" for risk in rule_m06.get("risks", [])),
            rule_m06.get("message", ""),
        )

        slot_m01 = call(tools, "query_slots", {"date": "2026-11-05", "desired_time": "18:00", "duration_minutes": 30})
        SAMPLES["slot_m01"] = slot_m01
        check(
            "时段-M01 18:00 冲突且有替代",
            slot_m01.get("available") is False and "19:00" in slot_m01.get("alternatives", []) and "20:00" in slot_m01.get("alternatives", []),
            f"conflicts={len(slot_m01.get('conflicts', []))}, alternatives={slot_m01.get('alternatives')}",
        )

        slot_m05 = call(tools, "query_slots", {"date": "2026-11-06", "desired_time": "18:00", "duration_minutes": 60})
        SAMPLES["slot_m05"] = slot_m05
        check(
            "时段-M05 全天占满无替代",
            slot_m05.get("available") is False and slot_m05.get("alternatives") == [],
            f"alternatives={slot_m05.get('alternatives')}",
        )

        slot_m04 = call(tools, "query_slots", {"date": "2026-11-07", "desired_time": "18:00", "duration_minutes": 30})
        check("时段-M04 可用", slot_m04.get("available") is True, slot_m04.get("message", ""))

        save_first = call(
            tools,
            "save_draft",
            {
                "material_id": "M01",
                "date": "2026-11-05",
                "time": "19:00",
                "status": "draft_pending_confirmation",
                "pending_confirmations": ["原要求 18:00 已占用，建议改为 19:00，待用户确认"],
            },
        )
        SAMPLES["save_first"] = save_first
        check(
            "保存-M01 成功且只保存草稿",
            save_first.get("ok") is True and save_first.get("duplicate") is False and "未发布" in save_first.get("message", ""),
            save_first.get("message", ""),
        )

        save_second = call(
            tools,
            "save_draft",
            {
                "material_id": "M01",
                "date": "2026-11-05",
                "time": "19:00",
                "status": "draft_pending_confirmation",
                "pending_confirmations": ["重复提交"],
            },
        )
        SAMPLES["save_second"] = save_second
        drafts_after_dup = store.list_drafts()
        check(
            "幂等-重复保存只保留一份",
            save_second.get("duplicate") is True and save_second.get("draft_id") == save_first.get("draft_id") and len(drafts_after_dup) == 1,
            f"draft_id={save_second.get('draft_id')}, drafts={len(drafts_after_dup)}",
        )

        save_blocked = call(
            tools,
            "save_draft",
            {"material_id": "M03", "date": "2026-11-05", "time": "20:00", "status": "draft"},
        )
        check(
            "保存-高风险拒绝",
            save_blocked.get("ok") is False and save_blocked.get("error_type") == "blocked_by_rules",
            save_blocked.get("message", ""),
        )

        save_incomplete = call(
            tools,
            "save_draft",
            {"material_id": "M02", "date": "2026-11-05", "time": "19:00", "status": "draft"},
        )
        check(
            "保存-缺字段拒绝",
            save_incomplete.get("ok") is False and save_incomplete.get("error_type") == "material_incomplete",
            save_incomplete.get("message", ""),
        )

        save_publish = call(
            tools,
            "save_draft",
            {"material_id": "M01", "date": "2026-11-10", "time": "10:00", "status": "published"},
        )
        check(
            "保存-拒绝发布状态",
            save_publish.get("ok") is False and save_publish.get("error_type") == "invalid_status",
            save_publish.get("message", ""),
        )

        fail_store = DataStore(data_dir=data_dir, fail_save=True)
        fail_tools = build_tools(fail_store)
        save_failed = call(
            fail_tools,
            "save_draft",
            {"material_id": "M01", "date": "2026-11-09", "time": "18:00", "status": "draft"},
        )
        SAMPLES["save_failed"] = save_failed
        check(
            "保存-故障注入如实失败",
            save_failed.get("ok") is False and save_failed.get("error_type") == "injected_failure" and len(fail_store.list_drafts()) == 1,
            f"error_type={save_failed.get('error_type')}, drafts={len(fail_store.list_drafts())}",
        )

        all_passed = all(item["passed"] for item in CHECKS)
        evidence = {
            "case": "p2-tools",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "all_passed": all_passed,
            "checks": CHECKS,
            "samples": SAMPLES,
        }
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        path = TRACES_DIR / "01-p2-tools.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        print(f"\nP2 GATE {'PASSED' if all_passed else 'FAILED'} ({sum(item['passed'] for item in CHECKS)}/{len(CHECKS)})")
        print(f"evidence: {path.relative_to(PROJECT_ROOT).as_posix()}")
        return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
