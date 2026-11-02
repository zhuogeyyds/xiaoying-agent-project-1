"""P5：模型接入与配置测试。"""

from __future__ import annotations

import pytest

from src.config import MODEL_NAME
from src.llm import ModelUnavailableError, create_chat_model


def test_model_name_is_user_confirmed() -> None:
    assert MODEL_NAME == "qwen3.8-max-0902"


def test_missing_key_raises_explicit_error(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(ModelUnavailableError) as excinfo:
        create_chat_model()

    assert excinfo.value.category == "密钥缺失"
    assert "DASHSCOPE_API_KEY" in str(excinfo.value)
    assert "Mock" in str(excinfo.value)
