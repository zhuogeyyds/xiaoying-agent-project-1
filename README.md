# 素材审核与发布排期 Agent（项目题 1）

帮助内容团队找出待处理素材，审核风险，形成无冲突、可确认的发布排期**草稿**。项目只保存草稿，不接真实发布。

> 分工：总体方案、业务规则、阶段闸门与关键决策由用户主导；AI 在用户设定的架构内完成实现、真实运行与文档初稿，用户逐阶段验收。

- 项目题号：1
- 运行形态：Python 命令行
- 框架：LangGraph 预构建 ReAct Agent（`langgraph.prebuilt.create_react_agent`）
- 模型：通义千问 `qwen3.8-max-0902`（用户确认可用并指定），温度 0
- 测试：pytest

## 评审入口

建议按这个顺序看：

1. [docs/03-evaluation.md](<docs/03-evaluation.md>)：验收点、预期/实际、证据路径、已知限制。
2. [examples/traces/01-m01-normal.json](<examples/traces/01-m01-normal.json>)：正常排期 + 18:00 冲突 → 模型第 6 步改建议 19:00 并标记待确认。
3. [examples/traces/05-m01-save-failure.json](<examples/traces/05-m01-save-failure.json>)：保存工具返回 `injected_failure`，模型如实报告失败。
4. [examples/traces/06-m01-duplicate.json](<examples/traces/06-m01-duplicate.json>)：重复提交返回已有 `D001`，草稿数保持 1。
5. [examples/traces/99-step-limit.json](<examples/traces/99-step-limit.json>)：步数上限触发 `incomplete`，runner note 列出已完成工具。
6. [examples/outputs/p4-summary.json](<examples/outputs/p4-summary.json>)：六个用例 16/16 自测汇总。
7. [examples/outputs/p7-summary.json](<examples/outputs/p7-summary.json>)：总验收 10 PASS / 0 FAIL / 2 PENDING 汇总。
8. [examples/traces/mock-01-m01-normal.json](<examples/traces/mock-01-m01-normal.json>)：离线 Mock 流程演示（`mode=mock`，不证明真实决策）。

## 环境

- Python 3.10+（本机用 3.10.9 验证）
- Windows / macOS / Linux 均可；命令以 PowerShell 为例
- 真实模型：通义千问 `qwen3.8-max-0902`，温度 0
- 依赖版本见 [requirements.txt](<requirements.txt>)

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux 把激活命令换成 `source .venv/bin/activate`。

## 配置密钥

密钥只从环境变量读取，不写入仓库、不落盘：

```powershell
$env:DASHSCOPE_API_KEY = "你的 DashScope 业务空间密钥"
$env:DASHSCOPE_API_BASE = "你的业务空间 OpenAI 兼容接口地址，以 /compatible-mode/v1 结尾"
```

- `DASHSCOPE_API_KEY` 未设置时，**真实模式**会明确报“密钥缺失”并停止，不自动降级；离线 Mock 必须显式加 `--offline-mock`。
- 不设置 `DASHSCOPE_API_BASE` 时默认使用 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
- [.env.example](<.env.example>) 只有变量名占位；真实值禁止提交。

## 运行命令

### 1. 真实模型冒烟

```powershell
python scripts/smoke_llm.py
```

成功输出 `SMOKE OK`，证据写 `examples/traces/00-llm-smoke.json`。

### 2. 跑单个用例

```powershell
python -m src.cli --case examples/cases/01-m01-normal.json
```

结果写入 `examples/traces/<case_id>.json` 与 `examples/outputs/<case_id>.json`。

### 3. 跑六个用例（P4 全套）

```powershell
python scripts/run_cases.py
```

脚本为每个用例准备独立数据副本；用例 06 复用用例 01 的副本，从而真实体现“同一素材同一天重复提交”。输出 `P4 GATE PASSED (16/16)`。

### 4. 工具直调自测（不经过模型）

```powershell
python scripts/check_p2.py
```

输出 `P2 GATE PASSED (23/23)`，证据写 `examples/traces/01-p2-tools.json`。

### 5. 测试

```powershell
python -m pytest -q
```

工具/存储测试不依赖网络；`test_step_limit_returns_incomplete` 会真实调用 `qwen3.8-max-0902`，运行前需要设置 `DASHSCOPE_API_KEY` 与 `DASHSCOPE_API_BASE`。

### 6. 一条命令总验收（P7）

```powershell
python scripts/final_check.py
```

依次运行六个用例和 pytest，再核对提交清单 11 项 + 题目补充的离线 Mock 检查，汇总写入 `examples/outputs/p7-summary.json`。

### 7. 离线 Mock（仅流程演示，不证明真实决策）

```powershell
python -m src.cli --case examples/cases/01-m01-normal.json --offline-mock
```

- 必须显式加 `--offline-mock`，不传就不会启用；
- 不调用真实模型，不进入 ReAct Agent，用真实工具和 store 按固定脚本演示流程；
- trace/output 标记 `mode: "mock"` 与边界说明；
- 真实模式缺少密钥时仍然明确报错并停止，**不会自动降级到 Mock**。

## 真实运行结果摘要

| 阶段 | 命令 | 真实结果 |
| --- | --- | --- |
| P1 模型冒烟 | `python scripts/smoke_llm.py` | `SMOKE OK model=qwen3.8-max-0902`，`PONG-QWEN38`，133 tokens |
| P2 工具直调 | `python scripts/check_p2.py` | `P2 GATE PASSED (23/23)` |
| P3 M01 | `python -m src.cli --case examples/cases/01-m01-normal.json` | `status=draft_saved`，D001 19:00 待确认 |
| P3 步数上限 | 低步数用例 | `status=incomplete`，已完成 read/check/query |
| P4 六条路径 | `python scripts/run_cases.py` | `P4 GATE PASSED (16/16)` |
| P5 测试 | `python -m pytest -q` | `14 passed`（[pytest-result.txt](<examples/outputs/pytest-result.txt>)） |
| P7 总验收 | `python scripts/final_check.py` | `P7 LOCAL ACCEPTANCE PASSED`（10 PASS / 0 FAIL / 2 PENDING） |

## 六条红线在代码中的落实

| 红线 | 落实位置 | 证据 |
| --- | --- | --- |
| 只保存草稿，不得出现“已发布” | [src/store.py](<src/store.py>) 只允许 `draft` / `draft_pending_confirmation`；[src/tools.py](<src/tools.py>) 不提供发布工具；trace 扫描禁用词 | [tests/test_tools.py](<tests/test_tools.py>) `test_no_publish_tool`；P4 六份 trace `red_line_ok=true` |
| 硬性发布时间不擅自更改 | 系统提示词；`query_slots` 返回冲突与替代；`save_draft` 拒绝冲突时段；替代时段写入待确认项 | `01-m01-normal` 第 4–7 步；`04-m01-conflict` |
| 缺字段或高风险阻断不保存 | [src/audit.py](<src/audit.py>) 规则引擎；`save_draft` 保存前再次校验 | `02-m02-missing`、`03-m03-risk` |
| 保存失败如实返回 | `save_draft` 返回 `ok=false` 与 `error_type`，不吞异常 | `05-m01-save-failure` |
| 相同素材同一天只保留一份草稿 | 幂等键 `material_id:date`，重复返回已有草稿编号 | `06-m01-duplicate`，drafts=1 |
| 剩余步数不足返回未完成与已完成部分 | `recursion_limit` + `pre_model_hook` 提醒 + `runner_note` | `99-step-limit`；`test_step_limit_returns_incomplete` |

## 与原始提示词的偏差（用户已确认）

| 项 | 原始提示词/方案 | 实际实现 | 原因 |
| --- | --- | --- | --- |
| 模型名 | `qwen-plus` | `qwen3.8-max-0902` | 用户只有该模型的可用额度，并明确指定 |
| 模型接入 | `ChatTongyi` | `ChatOpenAI` + OpenAI 兼容接口 | 用户业务空间只开放兼容接口；原生 DashScope `/api/v1` 调用返回 400 `url error` |
| 依赖 | 含 `dashscope`、`python-dotenv` | 不含 | 当前接入路径不使用这两个包；已在 `requirements.txt` 注释说明 |

## 实际用时与未完成部分

- **实际用时**：约 1 小时 50 分（2026-10-31 15:21–17:12），含环境安装、真实模型调试、P1–P7 阶段自测、离线 Mock 与等待确认；P7 本地总验收已通过。
- **未完成部分**：
  - 提交表单的最终 commit SHA（GitHub URL 已填；公开仓库无需授权）。
  - `trace.py` 未拆独立文件（记录逻辑在 `src/agent.py`）。
  - `SchedulingState` 的业务字段已定义，但运行中没有回写；trace 中的草稿由 `save_draft` 事件与 store 反推。

## 已知限制

1. **模型/接口偏差**：题目原约束是 ChatTongyi + qwen-plus；实际业务空间只开放 OpenAI 兼容接口，原生 `/api/v1` 返回 400 `url error`，因此改用 ChatOpenAI + `qwen3.8-max-0902`。该偏差经用户确认，细节见 [docs/02-solution.md](<docs/02-solution.md>)。
2. **框架弃用提示**：`create_react_agent` 在 langgraph 1.2.19 中已被标记 deprecated，官方建议 `langchain.agents.create_agent`；本项目按题目要求继续使用预构建 ReAct Agent，测试输出中会有一条 warning，不影响结果。
3. **模型行为不完全稳定**：同样的 M01 场景，个别运行会把草稿写成已占用的 18:00（被 `save_draft` 的冲突校验拒绝）。已通过系统提示词约束“草稿必须使用可用时段”缓解；P4 的 05 用例还移除了 18:00 占用以保证“前置流程正常”。这属于真实模型的不确定性，未用固定分支兜底。
4. **步数上限的最终提示是框架英文**：触发 `GraphRecursionError` 时，`final_output` 是框架的 `Sorry, need more steps...`；中文“未完成 + 已完成部分”在 `runner_note` 和 `task_status=incomplete` 中。
5. **数据是本地 JSON**：没有数据库、并发锁或多进程保护；写入使用临时文件 + `os.replace` 保证单进程原子性。
6. **只覆盖合成数据**：M01–M06 与五条规则是本地造的数据，不代表真实内容团队的完整规则库。
7. **离线 Mock 只验证流程**：`--offline-mock` 是显式入口，用固定脚本演示工具链，不能证明真实模型决策效果；真实模式仍使用 ReAct Agent，缺 key 会明确报错，不会自动降级。

## 目录

```text
README.md
requirements.txt
.env.example
src/
  config.py      模型名、温度、路径
  llm.py         ChatOpenAI 接入、错误归类、密钥检查
  audit.py       规则引擎（关键词/必填字段/时长）
  store.py       JSON 读写、幂等、冲突校验、失败注入
  tools.py       四个工具，无发布工具
  agent.py       ReAct Agent、系统提示词、步数守卫、运行记录
  cli.py         单用例命令行入口
scripts/
  smoke_llm.py   真实模型冒烟
  check_p2.py    P2 工具直调自测
  run_cases.py   P4 六用例真实运行
tests/           14 个 pytest 用例
examples/
  cases/         01–06 六个输入 + 99-step-limit
  traces/        真实运行记录
  outputs/       实际输出
data/            materials / rules / schedule / drafts
docs/            01-05 文档
```

## 文档索引

- [01-requirements.md](<docs/01-requirements.md>)：用户、目标、范围、六条成功标准
- [02-solution.md](<docs/02-solution.md>)：调用流程、动态决策、技术取舍、框架职责
- [03-evaluation.md](<docs/03-evaluation.md>)：验收点与 examples 路径、预期/实际、失败与限制
- [04-ai-usage.md](<docs/04-ai-usage.md>)：AI 辅助范围、个人修改、验证方式
- [05-retrospective.md](<docs/05-retrospective.md>)：最难问题、学习收获、下一步

## 提交信息

- 题号：1
- GitHub URL：https://github.com/zhuogeyyds/xiaoying-agent-project-1
- 最终 commit SHA：ecf5524e007bda68db0bf48c320d2266276d5cc5
- 私有仓库授权：公开仓库，无需授权

## 安全说明

- 仓库不包含真实密钥；`.env.example` 只有占位。
- `.gitignore` 已忽略 `.env`、`.dsh-drop/`、`*apiKey*.csv`。
- 运行所需的 key 只通过环境变量传入；trace/output 只记录“环境变量已设置，值不记录”。
- 如果拿到本项目的人要复现，请使用自己的 DashScope 业务空间密钥，不要把 key 写进任何文件。
