"""命令行入口：运行一个用例并输出结果与运行记录。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import run_case
from .store import DataStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="素材审核与发布排期 Agent（只保存草稿）")
    parser.add_argument("--case", required=True, help="用例 JSON 路径")
    parser.add_argument("--max-steps", type=int, default=None, help="覆盖用例中的步数上限")
    parser.add_argument(
        "--offline-mock",
        action="store_true",
        help="离线 Mock：仅验证工具与流程，不调用真实模型，不证明真实模型决策效果",
    )
    args = parser.parse_args(argv)

    case_path = Path(args.case)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    store = DataStore(fail_save=bool(case.get("fail_save", False)))

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.offline_mock:
        from .mock_runner import MOCK_BOUNDARY, run_mock_case

        trace = run_mock_case(store, case)
        print(f"MOCK {trace['case_id']} status={trace['task_status']} mode=mock")
        print(f"BOUNDARY: {MOCK_BOUNDARY}")
        print("\nFINAL OUTPUT:\n" + trace["final_output"])
        print(f"\nDRAFTS ({len(trace['drafts'])}):")
        for draft in trace["drafts"]:
            print(
                f"  {draft['draft_id']} {draft['material_id']} {draft['date']} {draft['time']} "
                f"status={draft['status']} pending={draft['pending_confirmations']}"
            )
        print(f"\nTRACE: {trace['trace_path']}")
        print(f"OUTPUT: {trace['output_path']}")
        return 0

    trace = run_case(store, case, max_steps=args.max_steps)

    print(f"RUN {trace['case_id']} status={trace['task_status']} steps={len(trace['events'])} "
          f"elapsed_ms={trace['elapsed_ms']} step_limit_hit={trace['step_limit_hit']} "
          f"red_line_ok={trace['red_line_ok']}")
    print("\nFINAL OUTPUT:\n" + (trace["final_output"] or "（无最终输出）"))
    if trace.get("runner_note"):
        print("\nRUNNER NOTE:\n" + trace["runner_note"])
    print(f"\nDRAFTS ({len(trace['drafts'])}):")
    for draft in trace["drafts"]:
        print(
            f"  {draft['draft_id']} {draft['material_id']} {draft['date']} {draft['time']} "
            f"status={draft['status']} pending={draft['pending_confirmations']}"
        )
    print(f"\nTRACE: {trace['trace_path']}")
    print(f"OUTPUT: {trace['output_path']}")
    if trace.get("error"):
        print(f"ERROR: {trace['error']}")

    if not trace["red_line_ok"]:
        return 2
    if trace["task_status"] == "error":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
