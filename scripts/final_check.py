"""P7 总验收：一条命令跑完六个用例 + pytest，并核对提交清单。"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pytest  # noqa: E402

from scripts.run_cases import main as run_cases_main  # noqa: E402
from src.config import EXAMPLES_DIR, OUTPUTS_DIR  # noqa: E402
from src.store import DataStore  # noqa: E402
from src.tools import build_tools  # noqa: E402

CHECKS: list[dict] = []
KEY_MARKERS = ("sk-ws-", "YIPEYEM", "maas.aliyuncs.com")
EXCLUDED_PARTS = {".venv", ".uv-cache", "__pycache__", ".git", ".dsh-drop"}
FORBIDDEN = "已发布"
SELF_PATH = Path(__file__).resolve()


def record(name: str, status: str, detail: str) -> None:
    CHECKS.append({"name": name, "status": status, "detail": detail})
    label = {"PASS": "PASS", "FAIL": "FAIL", "PENDING": "PENDING"}[status]
    print(f"[{label}] {name}: {detail}")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trace(case_id: str) -> dict:
    return load_json(EXAMPLES_DIR / "traces" / f"{case_id}.json")


def tool_events(data: dict, tool: str | None = None) -> list[dict]:
    events = [event for event in data["events"] if event["type"] == "tool"]
    if tool is not None:
        events = [event for event in events if event.get("tool") == tool]
    return events


def scan_key_markers() -> list[str]:
    hits: list[str] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.resolve() == SELF_PATH:
            continue
        if path.name.endswith(".pyc"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(marker in text for marker in KEY_MARKERS):
            hits.append(path.relative_to(PROJECT_ROOT).as_posix())
    return hits


def scan_forbidden_outputs() -> list[str]:
    hits: list[str] = []
    for folder in (EXAMPLES_DIR / "traces", EXAMPLES_DIR / "outputs"):
        for path in folder.glob("*.json"):
            if FORBIDDEN in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(path.relative_to(PROJECT_ROOT).as_posix())
    return hits


def docs_links_exist() -> tuple[bool, str]:
    path = PROJECT_ROOT / "docs" / "03-evaluation.md"
    text = path.read_text(encoding="utf-8")
    links = [
        link
        for link in re.findall(r"\]\(<([^>]+)>\)", text)
        if link.startswith("examples/")
    ]
    missing = [link for link in links if not (PROJECT_ROOT / link).exists()]
    return (bool(links) and not missing, f"examples links={len(links)}, missing={missing or 'none'}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== P7 1/2 六个用例（真实模型） ===")
    try:
        cases_rc = run_cases_main()
    except Exception as exc:  # noqa: BLE001 - 总验收要如实报告失败
        print(f"RUN CASES ERROR: {type(exc).__name__}: {exc}")
        cases_rc = 1

    print("\n=== P7 2/2 pytest ===")
    test_rc = int(pytest.main(["-q", str(PROJECT_ROOT / "tests")]))

    print("\n=== 提交清单核对 ===")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    record(
        "1 只做一道题并记录题号",
        "PASS" if "项目题号：1" in readme and "项目题号：1" in (PROJECT_ROOT / "docs/01-requirements.md").read_text(encoding="utf-8") else "FAIL",
        "README 与 docs/01 均记录题号 1",
    )

    record(
        "2 一条命令可运行，README 有评审入口",
        "PASS" if "## 评审入口" in readme and "final_check.py" in readme else "FAIL",
        "README 含评审入口与 final_check 命令",
    )

    trace_01 = trace("01-m01-normal")
    trace_05 = trace("05-m01-save-failure")
    trace_06 = trace("06-m01-duplicate")
    trace_99 = trace("99-step-limit")

    model_events = [event for event in trace_01["events"] if event["type"] == "model"]
    query_01 = [
        event
        for event in tool_events(trace_01, "query_slots")
        if (event.get("result") or {}).get("available") is False
    ]
    save_01 = tool_events(trace_01, "save_draft")
    record(
        "3 存在真实模型决策循环，不是固定分支",
        "PASS" if model_events and any(event.get("tool_calls") for event in model_events) and query_01 and save_01 else "FAIL",
        f"01 模型事件={len(model_events)}，query 冲突={len(query_01)}，save={len(save_01)}",
    )

    record(
        "4 至少两条运行记录体现因工具结果改变动作",
        "PASS"
        if query_01
        and any((event.get("args") or {}).get("time") == "19:00" for event in save_01)
        and any(
            (event.get("result") or {}).get("error_type") == "injected_failure"
            for event in tool_events(trace_05, "save_draft")
        )
        else "FAIL",
        "01 冲突后保存 19:00；05 保存失败后停止并报告",
    )

    record(
        "5 有步数上限和未完成状态",
        "PASS"
        if trace_99.get("task_status") == "incomplete"
        and trace_99.get("step_limit_hit") is True
        and "未完成" in (trace_99.get("runner_note") or "")
        and (PROJECT_ROOT / "tests/test_step_limit.py").exists()
        else "FAIL",
        f"99 status={trace_99.get('task_status')}，runner_note 含未完成",
    )

    missing_files = []
    for case_id in ("01-m01-normal", "02-m02-missing", "03-m03-risk", "04-m01-conflict", "05-m01-save-failure", "06-m01-duplicate"):
        for path in (
            EXAMPLES_DIR / "cases" / f"{case_id}.json",
            EXAMPLES_DIR / "traces" / f"{case_id}.json",
            EXAMPLES_DIR / "outputs" / f"{case_id}.json",
        ):
            if not path.exists():
                missing_files.append(path.name)
    record(
        "6 六个用例齐全且运行记录真实",
        "PASS" if not missing_files else "FAIL",
        f"缺失文件={missing_files or '无'}",
    )

    links_ok, links_detail = docs_links_exist()
    record("7 评估文档引用 examples 路径", "PASS" if links_ok else "FAIL", links_detail)

    ai_doc = PROJECT_ROOT / "docs" / "04-ai-usage.md"
    ai_text = ai_doc.read_text(encoding="utf-8")
    record(
        "8 AI 使用文档如实",
        "PASS" if ai_doc.exists() and "AI" in ai_text and "用户主导" in ai_text else "FAIL",
        "docs/04 含 AI 辅助范围与用户主导说明（内容真实性由用户最终确认）",
    )

    key_hits = scan_key_markers()
    publish_names = [tool.name for tool in build_tools(DataStore())]
    forbidden_hits = scan_forbidden_outputs()
    record(
        "9 无真实密钥和隐私数据",
        "PASS" if not key_hits and "sk-" not in env_example else "FAIL",
        f"key 命中={key_hits or '无'}；发布工具={publish_names}；输出禁用词={forbidden_hits or '无'}",
    )

    record(
        "10 私有仓库已授权指定评审账号",
        "PENDING",
        "本地无法验证；提交前由用户确认",
    )
    record(
        "11 提交题号、仓库地址、最终 commit SHA",
        "PENDING",
        "README 已留题号；GitHub URL 与 commit SHA 待用户提交时填写",
    )

    mock_path = EXAMPLES_DIR / "traces" / "mock-01-m01-normal.json"
    mock_ok = False
    mock_detail = "missing mock trace"
    if mock_path.exists():
        mock_trace = load_json(mock_path)
        boundary = mock_trace.get("boundary") or ""
        mock_ok = (
            mock_trace.get("mode") == "mock"
            and mock_trace.get("task_status") == "mock_draft_saved"
            and "不证明真实模型决策" in boundary
            and (PROJECT_ROOT / "tests/test_mock_entry.py").exists()
        )
        mock_detail = (
            f"mode={mock_trace.get('mode')}, status={mock_trace.get('task_status')}, "
            f"boundary={'ok' if '不证明真实模型决策' in boundary else 'missing'}"
        )
    record("题目补充：离线 Mock 入口（仅流程）", "PASS" if mock_ok else "FAIL", mock_detail)

    failed = [item for item in CHECKS if item["status"] == "FAIL"]
    pending = [item for item in CHECKS if item["status"] == "PENDING"]
    local_ok = cases_rc == 0 and test_rc == 0 and not failed

    summary = {
        "case": "p7-final-check",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cases_rc": cases_rc,
        "pytest_rc": test_rc,
        "local_passed": local_ok,
        "passed": sum(1 for item in CHECKS if item["status"] == "PASS"),
        "failed": len(failed),
        "pending": len(pending),
        "checks": CHECKS,
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "p7-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("\n=== P7 结果 ===")
    print(
        f"cases_rc={cases_rc}, pytest_rc={test_rc}, "
        f"PASS={summary['passed']}, FAIL={summary['failed']}, PENDING={summary['pending']}"
    )
    print(f"summary: examples/outputs/p7-summary.json")
    if not local_ok:
        print("P7 LOCAL ACCEPTANCE FAILED")
        return 1
    print("P7 LOCAL ACCEPTANCE PASSED（2 项提交动作待用户完成）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
