"""项目级常量与路径。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
TRACES_DIR = EXAMPLES_DIR / "traces"
OUTPUTS_DIR = EXAMPLES_DIR / "outputs"

# 用户确认可用并指定使用的通义千问模型（其业务空间只开放 OpenAI 兼容接口）。
MODEL_NAME = "qwen3.8-max-0902"
MODEL_TEMPERATURE = 0.0
