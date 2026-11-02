"""通义千问模型接入（OpenAI 兼容接口）。

背景：用户提供的 DashScope 业务空间只开放 OpenAI 兼容接口，原生 DashScope
Generation 接口返回 400 ``url error``；用户确认使用 ``qwen3.8-max-0902``。
因此这里用 ``ChatOpenAI`` 指向兼容接口，模型仍然是通义千问。

硬约束：
- 模型名来自 ``config.MODEL_NAME``，温度 0；
- 密钥只从环境变量 ``DASHSCOPE_API_KEY`` 读取，不写入仓库、不打印、不落盘；
- 真实模型不可用时抛出 ``ModelUnavailableError``，说明具体原因并停止，
  绝不静默降级到 Mock。
"""

from __future__ import annotations

import os
import re
from typing import Any

from langchain_openai import ChatOpenAI

from .config import MODEL_NAME, MODEL_TEMPERATURE

API_KEY_ENV = "DASHSCOPE_API_KEY"
API_BASE_ENV = "DASHSCOPE_API_BASE"
DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class ModelUnavailableError(RuntimeError):
    """真实模型不可用。``category`` 用于向用户说明该调整什么。"""

    def __init__(self, category: str, message: str, *, detail: str | None = None):
        self.category = category
        self.detail = detail
        super().__init__(message)


def api_key_status() -> str:
    """返回密钥来源说明，绝不返回值本身。"""
    if os.environ.get(API_KEY_ENV, "").strip():
        return f"环境变量 {API_KEY_ENV}（已设置，值不记录）"
    return f"环境变量 {API_KEY_ENV}（未设置）"


def api_base_status() -> str:
    if os.environ.get(API_BASE_ENV, "").strip():
        return f"环境变量 {API_BASE_ENV}（已设置，值不记录）"
    return "默认 DashScope OpenAI 兼容接口"


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise ModelUnavailableError(
            "密钥缺失",
            f"环境变量 {API_KEY_ENV} 未设置或为空，真实通义千问不可用。"
            "请先设置该环境变量后重试；本项目不做 Mock 降级，也不会继续执行。",
        )
    return key


def get_api_base() -> str:
    return os.environ.get(API_BASE_ENV, "").strip() or DEFAULT_API_BASE


def create_chat_model() -> ChatOpenAI:
    """创建 ChatOpenAI 客户端；任何不可用情况都以明确异常抛出。"""
    api_key = get_api_key()
    if not MODEL_NAME.strip():
        raise ModelUnavailableError("模型名错误", "config.MODEL_NAME 为空，无法调用模型。")
    try:
        return ChatOpenAI(
            model=MODEL_NAME,
            api_key=api_key,
            base_url=get_api_base(),
            temperature=MODEL_TEMPERATURE,
            # 关闭 SDK 自动重试：网络/额度问题立即暴露，由模型或用户决定下一步。
            max_retries=0,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - 需要原样暴露失败原因
        raise ModelUnavailableError(
            classify_model_error(exc),
            f"创建通义千问模型失败：{type(exc).__name__}: {exc}",
        ) from exc


_KEY_PATTERN = re.compile(
    r"invalid[\s_-]?api[\s_-]?key|incorrect api key|invalidapikey|"
    r"authentication|unauthorized|\b401\b",
    re.IGNORECASE,
)
_QUOTA_PATTERN = re.compile(
    r"insufficient[\s_-]?quota|arrearage|quota|throttl|rate[\s_-]?limit|"
    r"balance|good standing|free[\s_-]?tier|overdue|billing",
    re.IGNORECASE,
)
_MODEL_PATTERN = re.compile(
    r"model[\s_-]?not[\s_-]?(exist|found)|modelnotfound|unknown model|"
    r"invalid model|no such model|does not exist",
    re.IGNORECASE,
)
_ENDPOINT_PATTERN = re.compile(
    r"invalid url|url[\s_-]?error|api[\s_-]?base|endpoint|"
    r"\b404\b|not found",
    re.IGNORECASE,
)
_NETWORK_PATTERN = re.compile(
    r"connection|connect|timed? ?out|ssl|getaddrinfo|name resolution|"
    r"network|proxy|max retries|handshake|temporarily unavailable",
    re.IGNORECASE,
)


def _error_text(exc: BaseException) -> str:
    """拼接异常链与响应体，用于归类，不用于直接展示密钥。"""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    for _ in range(6):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        response = getattr(current, "response", None)
        if response is not None:
            parts.append(f"status={getattr(response, 'status_code', '')}")
            try:
                parts.append(str(response.text)[:500])
            except Exception:  # noqa: BLE001 - 响应体仅用于诊断
                pass
        body = getattr(current, "body", None)
        if body is not None:
            parts.append(str(body)[:500])
        code = getattr(current, "code", None)
        if code:
            parts.append(str(code))
        current = current.__cause__ or current.__context__
    return "\n".join(parts)


def classify_model_error(exc: BaseException) -> str:
    """把底层异常归为可操作的原因类别。"""
    text = _error_text(exc)
    if _KEY_PATTERN.search(text):
        return "密钥无效"
    if _QUOTA_PATTERN.search(text):
        return "额度不足"
    if _MODEL_PATTERN.search(text):
        return "模型名错误"
    if _ENDPOINT_PATTERN.search(text):
        return "接口地址错误"
    if _NETWORK_PATTERN.search(text):
        return "网络不通"
    return "模型调用失败"


def explain_model_error(exc: BaseException) -> str:
    """生成面向用户的多行错误说明（不含密钥）。"""
    if isinstance(exc, ModelUnavailableError):
        prefix = f"[{exc.category}] "
        return prefix + str(exc)
    category = classify_model_error(exc)
    return f"[{category}] 真实通义千问调用失败：{type(exc).__name__}: {exc}"


def extract_text(message: Any) -> str:
    """兼容 AIMessage.content 为字符串或分段列表的情况。"""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)
    return str(content)
