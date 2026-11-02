"""P1 冒烟：用真实通义千问 qwen3.8-max-0902 验证模型可用。

用法：
    python scripts/smoke_llm.py

成功退出码 0；密钥缺失等配置问题退出码 2；其他调用失败退出码 1。
运行结果写入 examples/traces/00-llm-smoke.json（失败时写对应文件）。
本脚本不做任何 Mock 降级，也不打印密钥。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import MODEL_NAME, MODEL_TEMPERATURE, TRACES_DIR  # noqa: E402
from src.llm import (  # noqa: E402
    ModelUnavailableError,
    api_base_status,
    api_key_status,
    classify_model_error,
    create_chat_model,
    explain_model_error,
    extract_text,
)

PROMPT = "这是一次连通性测试。请只回复：PONG-QWEN38"
MARKER = "PONG-QWEN38"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(record: dict, name: str) -> Path:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACES_DIR / name
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    base_record = {
        "case": "llm-smoke",
        "timestamp": _now(),
        "model": MODEL_NAME,
        "temperature": MODEL_TEMPERATURE,
        "api_key_source": api_key_status(),
        "api_base_source": api_base_status(),
        "prompt": PROMPT,
    }

    try:
        model = create_chat_model()
    except ModelUnavailableError as exc:
        record = {
            **base_record,
            "status": "blocked",
            "category": exc.category,
            "error": str(exc),
            "note": "真实模型不可用，已停止；未使用 Mock 降级。",
        }
        path = _write(record, "00-llm-smoke-blocked.json")
        print(f"SMOKE BLOCKED category={exc.category}")
        print(f"reason: {exc}")
        print(f"evidence: {path.relative_to(PROJECT_ROOT).as_posix()}")
        return 2

    started = time.perf_counter()
    try:
        message = model.invoke(PROMPT)
    except Exception as exc:  # noqa: BLE001 - 原样暴露真实失败
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        record = {
            **base_record,
            "status": "failed",
            "category": getattr(exc, "category", None) or classify_model_error(exc),
            "error": explain_model_error(exc),
            "latency_ms": elapsed_ms,
            "note": "真实模型调用失败，已停止；未使用 Mock 降级。",
        }
        path = _write(record, "00-llm-smoke-error.json")
        print("SMOKE FAILED")
        print(explain_model_error(exc))
        print(f"evidence: {path.relative_to(PROJECT_ROOT).as_posix()}")
        return 1

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    text = extract_text(message).strip()
    usage = getattr(message, "usage_metadata", None)
    response_metadata = getattr(message, "response_metadata", None) or {}
    request_id = response_metadata.get("request_id")
    ok = MARKER in text.upper()

    record = {
        **base_record,
        "status": "ok" if ok else "unexpected_response",
        "latency_ms": elapsed_ms,
        "response": text,
        "marker_expected": MARKER,
        "marker_found": ok,
        "usage": usage,
        "request_id": request_id,
        "response_metadata": response_metadata,
        "note": "真实 DashScope 调用，未使用 Mock。",
    }
    path = _write(record, "00-llm-smoke.json")

    print(f"SMOKE {'OK' if ok else 'UNEXPECTED_RESPONSE'} model={MODEL_NAME}")
    print(f"latency_ms={elapsed_ms}")
    if usage:
        print(f"usage={json.dumps(usage, ensure_ascii=False)}")
    print(f"response: {text}")
    print(f"evidence: {path.relative_to(PROJECT_ROOT).as_posix()}")
    if not ok:
        print(f"expected marker not found: {MARKER}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
