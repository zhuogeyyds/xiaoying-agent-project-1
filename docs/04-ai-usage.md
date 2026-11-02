# 04 AI 使用与分工说明

## 项目分工

本项目采用“用户定方案与验收、AI 做实现与验证”的协作方式：

| 角色 | 负责内容 |
| --- | --- |
| 用户（项目负责人） | 提供题目与《方案文档》，确定总体架构、技术选型、数据设计、四个工具边界、六条红线、六条执行路径和阶段闸门；决定模型/接口与密钥使用方式；逐阶段验收真实运行输出；确认实现偏差；决定提交范围 |
| AI 编码助手 | 在用户给定的架构内完成代码实现、合成数据、命令行入口、运行记录、pytest 测试和文档初稿；执行真实模型调用与自测；定位并修复实现问题 |
| 共同确认 | 模型/接口调整、阶段通过标准、已知限制的保留方式、提交材料 |

项目的总体架构由用户给出，AI 的职责是**在用户设定的架构内实现和验证**，而不是自行设计架构。这样既保证方案与业务判断来自人，也让重复性编码、真实运行和证据整理交给 AI。

## 使用的 AI 工具

- 工具：DeepSeek Harness 编码 Agent（deepseek-flash 模型），在 Windows 本机工作区中运行。
- 使用时间：2026-10-31，约 1 小时 25 分钟（P1–P6）。
- 使用方式：用户给出 P0 总控提示词、《方案文档》、题目和分阶段指令；AI 按阶段实现、运行、报告；用户确认后才进入下一阶段。

## 用户主导的工作

### 1. 总体架构与方案

用户在《方案文档》中确定了本项目的整体搭建思路，包括：

- 运行形态：Python 命令行，一条命令可复现；
- 框架：LangGraph 预构建 ReAct Agent，利用其“模型选动作 → 工具执行 → 观察结果 → 再决策”的循环；
- 模型接入：通义千问、温度 0、密钥只读环境变量；
- 目录结构：`src / tests / examples / data / docs` 的职责划分；
- 合成数据：M01–M06 六个素材、五条规则、已有排期、草稿表；
- 工具边界：读取素材、检查规则、查询时段、保存草稿，明确不提供发布工具；
- 六条红线：只保存草稿、硬性时间不改、缺字段/高风险阻断、失败如实返回、同日幂等、步数不足返回未完成；
- 六条执行路径：正常+冲突、信息缺失、规则风险、时段冲突、保存失败、重复提交；
- 阶段自测闸门：P1–P7 每阶段先过闸门，未通过不进入下一阶段；离线 Mock 作为题目补充单独验证。
- 文档与提交清单：README、五份文档、examples 证据、GitHub 提交要求。

这些内容不是 AI 自行发挥的，而是用户方案文档中的明确设计。AI 在实现过程中遇到与方案不一致的地方（例如业务空间只支持 OpenAI 兼容接口），会先报告，由用户确认后再调整。

### 2. 关键决策

- **模型与接口**：用户明确只有 `qwen3.8-max-0902` 的额度；原生 DashScope `/api/v1` 返回 400 `url error` 后，用户确认改用 ChatOpenAI 指向业务空间的 OpenAI 兼容接口，并在 README、`requirements.txt`、方案文档中如实记录偏差。
- **阶段流程**：用户要求“每阶段完成先停下，报告改了哪些文件、运行命令、真实输出、逐条判据”，确认后才进入下一阶段。AI 在 P1–P3 曾连续推进，用户指出后恢复该流程，P4–P6 均按阶段验收。
- **偏差处理**：用户接受 P3 的 `trace.py` 未拆分、业务状态未回写、步数上限英文提示三处偏差，要求“以真实工程情况为主”写进评估文档，而不是隐藏。
- **密钥与提交**：用户提供业务空间密钥，要求只通过环境变量调用；两份带密钥的 CSV 已按用户要求删除；GitHub 提交、私有仓库授权由用户完成。

### 3. 阶段验收

用户对每个阶段的真实输出做了验收，确认后才进入下一阶段：

| 阶段 | 用户验收的内容 |
| --- | --- |
| P1 | 目录、依赖、`llm.py` 创建模型、真实冒烟 `SMOKE OK` |
| P2 | 四份数据、四个工具、六种返回、幂等、无发布工具（23/23） |
| P3 | M01 真实链路、运行记录、步数上限（5/5） |
| P4 | 六个用例、六份 trace/output、路径一/五/六的关键行为（16/16） |
| P5 | 14 个 pytest 测试全绿 |
| P6 | README 与五份文档、验收点路径对照、密钥清理 |

本项目的验收以“阶段闸门 + 真实运行输出”为准，不以“逐行手写代码”为标准。代码实现由 AI 完成；用户负责方案、关键决策、阶段验收和最终提交。若用户在提交前对具体文件做了逐行复核，可在本节补充文件清单与复核结论，进一步如实呈现个人贡献。

## AI 辅助的工作

AI 起草或修改了以下内容：

| 范围 | 文件 |
| --- | --- |
| 脚手架与依赖 | `README.md`、`requirements.txt`、`.env.example`、`.gitignore`、目录结构 |
| 模型接入 | `src/config.py`、`src/llm.py`、`scripts/smoke_llm.py` |
| 数据与规则 | `data/materials.json`、`rules.json`、`schedule.json`、`drafts.json` |
| 工具与存储 | `src/audit.py`、`src/store.py`、`src/tools.py`、`scripts/check_p2.py` |
| Agent 与运行记录 | `src/agent.py`、`src/mock_runner.py`、`src/cli.py`、`scripts/run_cases.py` |
| 离线 Mock | `src/mock_runner.py`、`tests/test_mock_entry.py`、`examples/traces/mock-*.json` |
| 六条路径 | `examples/cases/01–06`、`examples/traces/*`、`examples/outputs/*` |
| 测试 | `tests/conftest.py`、`tests/test_tools.py`、`tests/test_step_limit.py`、`tests/test_llm_config.py`、`tests/test_mock_entry.py` |
| 文档 | `docs/01–05`、README 提交版 |

## 验证方式

每一阶段结论都以真实运行输出为依据，没有手写预期结果：

| 验证 | 命令 | 结果 |
| --- | --- | --- |
| 模型真实调用 | `python scripts/smoke_llm.py` | `SMOKE OK`，`PONG-QWEN38`，133 tokens |
| 工具直调 | `python scripts/check_p2.py` | `P2 GATE PASSED (23/23)` |
| 六条路径 | `python scripts/run_cases.py` | `P4 GATE PASSED (16/16)` |
| 测试 | `python -m pytest -q` | `14 passed`（[pytest-result.txt](<examples/outputs/pytest-result.txt>)） |
| 总验收 | `python scripts/final_check.py` | `P7 LOCAL ACCEPTANCE PASSED`，10 PASS / 0 FAIL / 2 PENDING |
| 离线 Mock | `python -m src.cli --case examples/cases/01-m01-normal.json --offline-mock` | `mode=mock`，边界“不证明真实模型决策” |
| 密钥扫描 | 全项目 `sk-`/`apiKey` 扫描 | 项目文件无命中；两份 CSV 已删除 |

另外做了人工核对：

- 逐条读 `examples/traces/01-m01-normal.json` 的 8 个事件，确认第 5 步冲突、第 6 步改 19:00；
- 逐条读 05 的 `save_draft` 结果，确认 `injected_failure` 且模型没有改写成功；
- 读 06 的 `save_draft` 结果，确认 `duplicate=true` 且 `drafts=1`；
- 扫描 `examples/traces`、`examples/outputs`，确认没有“已发布”。

## AI 使用中的问题与处理

1. **AI 连续推进阶段**：P1–P3 没有按 P0 每阶段停下，用户指出后恢复逐阶段确认；P4–P6 每阶段结束都提交四样东西：改了哪些文件、运行命令、真实输出、逐条判据结论。
2. **AI 误判“未完成”**：P4 第一次把阻断/失败摘要里的“未完成”当成步数上限，导致 03/05 状态错误。判断为代码问题后直接修判定逻辑，复跑通过。
3. **AI 依赖模型措辞判断步数**：P5 第一次步数测试失败，改为在 `pre_model_hook` 记录实际 `remaining_steps`，不再依赖文字。
4. **模型非确定性**：05 用例中模型曾把草稿保存到已占用时段，AI 先加提示词约束，再调整测试夹具让前置流程正常；没有写固定分支兜底。

## 声明

- 本文档如实记录 AI 辅助范围与用户主导内容，不把 AI 生成的代码/文档说成用户手写。
- 总体方案、业务规则、阶段闸门和关键决策来自用户；代码、运行脚本和文档初稿由 AI 在用户方案内完成，并经用户逐阶段验收。
- AI 生成的代码和文档仍可能有错误；用户应在提交前自行审阅。面试中如被追问架构细节，建议用户结合《方案文档》和自己的决策过程回答，而不是背诵 AI 生成的实现细节。
- 项目没有提交真实密钥、隐私数据或用户业务数据；素材与规则均为合成数据。
