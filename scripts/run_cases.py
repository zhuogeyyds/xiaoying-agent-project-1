"""P4：逐个真实运行六个用例，保存输出与运行记录，并核对验收点。

每个用例使用独立的数据副本，避免相互污染；路径六复用路径一的数据副本，
从而真实体现“同一素材同一天重复提交”。
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

from src.agent import run_case  # noqa: E402
from src.config import DATA_DIR, EXAMPLES_DIR, OUTPUTS_DIR, TRACES_DIR  # noqa: E402
from src.store import DataStore  # noqa: E402

CASE_IDS = [
    "01-m01-normal",
    "02-m02-missing",
    "03-m03-risk",
    "04-m01-conflict",
    "05-m01-save-failure",
    "06-m01-duplicate",
]

CHECKS: list[dict] = []


def check(name: str, condition: bool, detail: str) -> None:
    CHECKS.append({"name": name, "passed": bool(condition), "detail": detail})
    print(f"[{'PASS' if condition else 'FAIL'}] {name}: {detail}")


def load_case(case_id: str) -> dict:
    path = EXAMPLES_DIR / "cases" / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fresh_workdir(base: Path, name: str) -> Path:
    workdir = base / name
    workdir.mkdir(parents=True, exist_ok=True)
    for filename in ("materials.json", "rules.json", "schedule.json"):
        shutil.copy(DATA_DIR / filename, workdir / filename)
    (workdir / "drafts.json").write_text('{\n  "drafts": []\n}\n', encoding="utf-8")
    return workdir


def remove_schedule_entry(workdir: Path, date: str, time: str) -> None:
    """为保存失败用例准备“前置流程正常”的排期：移除目标时段的占用。"""
    path = workdir / "schedule.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schedule"] = [
        entry
        for entry in data.get("schedule", [])
        if not (entry.get("date") == date and entry.get("time") == time)
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tool_events(trace: dict, tool: str | None = None) -> list[dict]:
    events = [event for event in trace["events"] if event["type"] == "tool"]
    if tool is not None:
        events = [event for event in events if event.get("tool") == tool]
    return events


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        w01 = fresh_workdir(base, "01")
        w02 = fresh_workdir(base, "02")
        w03 = fresh_workdir(base, "03")
        w04 = fresh_workdir(base, "04")
        w05 = fresh_workdir(base, "05")
        # 路径五要求“前置流程正常，保存时注入失败”：移除 18:00 占用，让保存本身失败。
        remove_schedule_entry(w05, "2026-11-05", "18:00")

        runs: dict[str, dict] = {}
        runs["01-m01-normal"] = run_case(DataStore(w01), load_case("01-m01-normal"))
        runs["02-m02-missing"] = run_case(DataStore(w02), load_case("02-m02-missing"))
        runs["03-m03-risk"] = run_case(DataStore(w03), load_case("03-m03-risk"))
        runs["04-m01-conflict"] = run_case(DataStore(w04), load_case("04-m01-conflict"))
        runs["05-m01-save-failure"] = run_case(
            DataStore(w05, fail_save=True), load_case("05-m01-save-failure")
        )
        # 路径六复用路径一的数据副本：那里已经有一份 M01/2026-11-05 草稿。
        runs["06-m01-duplicate"] = run_case(DataStore(w01), load_case("06-m01-duplicate"))

        r01, r02, r03 = runs["01-m01-normal"], runs["02-m02-missing"], runs["03-m03-risk"]
        r04, r05, r06 = runs["04-m01-conflict"], runs["05-m01-save-failure"], runs["06-m01-duplicate"]

        check("01 正常排期状态", r01["task_status"] == "draft_saved", f"status={r01['task_status']}")
        check(
            "01 冲突后建议 19:00 并标记待确认",
            any(event.get("tool") == "save_draft" and (event.get("args") or {}).get("time") == "19:00" for event in tool_events(r01))
            and any((draft.get("pending_confirmations") or []) for draft in r01["drafts"]),
            f"drafts={[(d['time'], d['status']) for d in r01['drafts']]}",
        )
        check(
            "01 无发布完成表述",
            r01["red_line_ok"] is True,
            f"red_line_ok={r01['red_line_ok']}",
        )

        check("02 信息缺失阻断", r02["task_status"] == "blocked", f"status={r02['task_status']}")
        check("02 未保存草稿", len(r02["drafts"]) == 0, f"drafts={len(r02['drafts'])}")

        check("03 高风险阻断", r03["task_status"] == "blocked", f"status={r03['task_status']}")
        check(
            "03 输出规则编号 R01",
            any(
                risk.get("rule_id") == "R01"
                for event in tool_events(r03, "check_rules")
                for risk in (event.get("result") or {}).get("risks", [])
            ),
            "check_rules risks",
        )
        check("03 未保存草稿", len(r03["drafts"]) == 0, f"drafts={len(r03['drafts'])}")

        check("04 时段冲突后建议 19:00", r04["task_status"] == "draft_saved", f"status={r04['task_status']}")
        check(
            "04 冲突查询与替代时段",
            any(
                event.get("tool") == "query_slots"
                and (event.get("result") or {}).get("available") is False
                and (event.get("result") or {}).get("alternatives")
                for event in tool_events(r04)
            ),
            "query_slots conflict",
        )

        check("05 保存失败状态", r05["task_status"] == "save_failed", f"status={r05['task_status']}")
        check(
            "05 保存失败如实返回",
            any(
                (event.get("result") or {}).get("error_type") == "injected_failure"
                for event in tool_events(r05, "save_draft")
            )
            and "失败" in r05["final_output"],
            "save_draft injected_failure",
        )
        check("05 未写入草稿", len(r05["drafts"]) == 0, f"drafts={len(r05['drafts'])}")

        check("06 重复提交状态", r06["task_status"] == "draft_saved", f"status={r06['task_status']}")
        check(
            "06 返回已有草稿且标记重复",
            any((event.get("result") or {}).get("duplicate") is True for event in tool_events(r06, "save_draft")),
            "save_draft duplicate",
        )
        check("06 草稿数为一", len(r06["drafts"]) == 1, f"drafts={len(r06['drafts'])}")

        all_passed = all(item["passed"] for item in CHECKS)
        summary = {
            "case": "p4-six-cases",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "all_passed": all_passed,
            "cases": {
                case_id: {
                    "status": run["task_status"],
                    "drafts": len(run["drafts"]),
                    "trace": f"examples/traces/{case_id}.json",
                    "output": f"examples/outputs/{case_id}.json",
                }
                for case_id, run in runs.items()
            },
            "checks": CHECKS,
        }
        (OUTPUTS_DIR / "p4-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        print(f"\nP4 GATE {'PASSED' if all_passed else 'FAILED'} ({sum(item['passed'] for item in CHECKS)}/{len(CHECKS)})")
        print("summary: examples/outputs/p4-summary.json")
        return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
