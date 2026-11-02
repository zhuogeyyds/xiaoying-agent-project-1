# 02 方案

## 方案来源与分工

本项目的总体方案由用户提供并确认，来源是用户的《方案文档》。用户确定的内容包括：

- 选题与目标：项目题 1“素材审核与发布排期 Agent”，只保存草稿、不接真实发布；
- 技术选型：Python 命令行、LangGraph 预构建 ReAct Agent、通义千问、温度 0、密钥只读环境变量；
- 工程结构：`src / tests / examples / data / docs` 的目录职责；
- 数据设计：M01–M06 六个素材、五条规则、已有排期、草稿表；
- 工具边界：读取素材、检查规则、查询时段、保存草稿，明确不提供发布工具；
- 决策循环：模型选动作 → 执行工具 → 观察结果 → 调整或结束；
- 六条红线、六条执行路径、阶段自测闸门和文档清单。

AI 在用户设定的框架内完成代码实现、真实运行、问题定位与文档初稿；用户逐阶段验收真实运行输出，并对模型/接口调整、实现偏差和提交范围做最终决策。这样分工既保留了用户对架构和验收的主导，也让 AI 承担重复性实现与验证工作。

## 总体调用流程

```text
python -m src.cli --case examples/cases/01-m01-normal.json
        |
        v
读取用例 JSON（素材编号、日期、时段、硬性要求、步数上限、失败注入）
        |
        v
DataStore(data/)  ──>  materials.json / rules.json / schedule.json / drafts.json
        |
        v
build_tools(store) ──> read_material / check_rules / query_slots / save_draft
        |
        v
ChatOpenAI(model=qwen3.8-max-0902, temperature=0, base_url=业务空间兼容接口)
        |
        v
create_react_agent(model, tools, prompt=SYSTEM_PROMPT, state_schema=SchedulingState)
        |
        v
agent.stream(..., stream_mode="updates", config={"recursion_limit": max_steps})
        |
        +--> 每个事件写入 trace：模型动作、工具名、参数、结果、摘要
        |
        v
task_status + drafts + pending_confirmations
        |
        v
examples/traces/<case_id>.json
examples/outputs/<case_id>.json
```

## 组件职责

| 组件 | 职责 |
| --- | --- |
| [src/cli.py](<src/cli.py>) | 单用例入口；加载用例、选择数据目录、调用 `run_case`、打印结果 |
| [src/agent.py](<src/agent.py>) | 系统提示词、`SchedulingState`、ReAct Agent 组装、步数守卫、流式事件收集、trace/output 落盘 |
| [src/llm.py](<src/llm.py>) | 创建 ChatOpenAI；只从环境变量读 key/base；错误归类（密钥、额度、模型名、地址、网络） |
| [src/tools.py](<src/tools.py>) | 四个 LangChain 工具，薄封装 store；统一结构化返回，不抛裸异常 |
| [src/audit.py](<src/audit.py>) | 规则引擎：关键词、必填字段、超长时长；输出 risks / blocked / needs_supplement |
| [src/store.py](<src/store.py>) | JSON 读写、时段冲突、草稿幂等、状态白名单、保存失败注入 |
| [src/config.py](<src/config.py>) | 模型名、温度、路径常量 |

## 动态决策

系统提示词只给约束和工具说明，不规定固定步骤。模型每一步可以自己选：

- 先读素材，或同时读素材 + 查规则；
- 规则不通过时直接结束，不查时段、不保存；
- 规则通过后查时段；
- 时段被占用时改建议替代时段，或在冲突结果后调整；
- 保存失败时停止并如实报告，或按自己的判断重试一次；
- 信息不足时直接阻断。

真实运行中出现的不同路径：

| 用例 | 模型实际动作 |
| --- | --- |
| 01 M01 正常+冲突 | `read_material` + `check_rules` 并行 → `query_slots(18:00)` → 看到 M00 占用 → `save_draft(19:00, draft_pending_confirmation)` |
| 02 M02 缺字段 | `read_material` → `check_rules` 返回 R02 阻断 → 直接结束，不查时段、不保存 |
| 03 M03 医疗风险 | `read_material` → `check_rules` 返回 R01 高风险 → 直接结束，不保存 |
| 04 M01 冲突用例 | 与 01 同素材，强调“替代而非覆盖”；模型查 18:00 后保存 19:00 待确认 |
| 05 M01 保存失败 | 前置流程正常 → `save_draft` 返回 `injected_failure` → 模型停止重试并如实报告失败 |
| 06 M01 重复提交 | 复用 01 的草稿状态 → `save_draft` 返回 `duplicate=true, draft_id=D001` → 模型说明未新增 |

“模型选动作 → 执行工具 → 观察结果 → 调整下一步或结束”的证据在 trace 的 `events` 里：每条模型事件有 `tool_calls`，紧随其后的工具事件有 `result` 与 `summary`，下一条模型事件的内容能看出它如何依据上一条结果调整。

## 技术取舍

### 为什么用 LangGraph 预构建 ReAct Agent

- 题目只有四个工具、状态简单；预构建 Agent 已覆盖“模型选工具 → ToolNode 执行 → 回到模型”的循环，不需要自己画图。
- 它自带 `remaining_steps` 管理和流式 `updates`，方便做步数上限与运行记录。
- 评审真正要看的是动态决策，而不是图结构；把精力放在提示词、工具边界、trace 和测试上更划算。

### 为什么不用自定义图

自定义图会增加节点、边、条件分支代码，且很容易把“模型决策”写成固定分支，反而偏离题目要求。预构建 Agent 的循环是真实的模型驱动；我们只在外面加步数守卫和记录，不替模型做业务决策。

### 模型与接口：为什么不是 ChatTongyi

题目原方案是 `ChatTongyi + qwen-plus`。实际执行时：

1. 用户提供的业务空间只开放 OpenAI 兼容接口；
2. 原生 DashScope `https://<workspace>/api/v1` 调 `qwen3.8-max-0902` 返回 `400 InvalidParameter: url error`；
3. 同一业务空间的 `/compatible-mode/v1` 返回 200，并支持 tool calling；
4. 用户明确表示只有 `qwen3.8-max-0902` 的额度，要求后续都按这个模型。

因此改用 `ChatOpenAI(base_url=兼容接口)`，模型仍是通义千问，温度 0。该偏差已由用户确认，`requirements.txt` 与 README 都写明了原因；`dashscope`、`python-dotenv` 在当前路径不使用，所以没有安装。

### 为什么用本地 JSON 而不是数据库

- 题目规模小，JSON 可直接阅读、可直接作为示例数据；
- 写入用临时文件 + `os.replace`，单进程下保证原子性；
- 幂等键 `material_id:date` 在 `save_draft` 内检查，重复提交返回已有草稿编号；
- 代价是没有并发锁，不适合生产多进程，这一点写在已知限制里。

### 步数上限的双保险

- 外层：`config={"recursion_limit": max_steps}`，由 LangGraph 硬截断；
- 内层：`pre_model_hook` 在 `remaining_steps <= 3` 时追加“剩余步数不足”提醒，要求模型停止工具调用、返回未完成与已完成部分；
- 运行器：捕获 `GraphRecursionError` / 未执行的 tool calls，设置 `task_status=incomplete`，生成 `runner_note` 列出已完成的工具。

### 离线 Mock 入口

题目要求“模型不可用时提供离线 Mock 入口并标明边界”。本项目增加了一个**显式**入口：

```powershell
python -m src.cli --case examples/cases/01-m01-normal.json --offline-mock
```

设计边界：

- 只有传 `--offline-mock` 才进入 [src/mock_runner.py](<src/mock_runner.py>)，不传就绝不启用；
- 不调用真实模型，也不进入 `create_react_agent`；使用真实 `DataStore` 和四个真实工具，按固定脚本演示“读取→审核→查时段→保存/阻断/失败”；
- trace/output 标记 `mode: "mock"` 与 `boundary: "仅验证工具与流程，不证明真实模型决策效果"`；
- 写入 `examples/traces/mock-*.json`、`examples/outputs/mock-*.json`，不覆盖 01–06 的真实 trace；
- 真实模式缺少密钥时仍然明确报错并停止，**不会自动落到 Mock**。

没有把 Mock 做成假 LLM 去跑 `create_react_agent`，是为了避免“用固定脚本冒充 ReAct 决策”。Mock 的定位就是流程演示；真实决策证据只来自 01–06 的真实模型 trace。

### 运行记录（trace）设计

`trace` 记录：

- `model` / `temperature` / `max_steps` / `input`；
- 每条事件：步骤号、类型（model/tool）、工具名、参数、结构化结果、结果摘要；
- 模型可见文字说明（不记录内部思维过程）；
- 最终 `task_status`、`drafts`、`pending_confirmations`、`step_limit_hit`、`runner_note`、`red_line_ok`。

没有单独拆 `trace.py`，记录逻辑在 [src/agent.py](<src/agent.py>)；这是实现上的偏差，不影响“流式事件真实产生”。

## 业务状态

```python
class SchedulingState(AgentState):
    task_status: str
    drafts: list[dict]
    pending_confirmations: list[str]
```

`AgentState` 已提供 `messages` 与 `remaining_steps`，满足题目“保留消息字段和剩余步数字段”。当前实现的 `drafts` / `pending_confirmations` 主要由 `save_draft` 事件和 store 反推，运行中没有回写状态；这一点如实写在评估文档的已知限制里。

## 数据与规则

### 素材

| 素材 | 特征 | 用途 |
| --- | --- | --- |
| M01 | 完整、无风险、要求 2026-11-05 18:00 | 正常排期 + 时段冲突 |
| M02 | 缺 `duration_minutes`、`category` | 信息缺失阻断 |
| M03 | 标题/描述含医疗宣称 | 高风险 R01 阻断 |
| M04 | 含医疗宣称，但时段可用 | 风险独立于时段 |
| M05 | 低风险，但 2026-11-06 全天排满 | 无替代时段的冲突 |
| M06 | 缺 `source_license` | 需补充资料阻断 |

### 规则

| 规则 | 类型 | 等级 | 动作 | 说明 |
| --- | --- | --- | --- | --- |
| R01 | 关键词 | high | block | 医疗宣称：治疗/疗效/治愈/处方/药到病除 |
| R02 | 必填字段 | high | block | duration_minutes/category/publish_date/requested_time |
| R03 | 关键词 | medium | confirm | 绝对化用语 |
| R04 | 必填字段 | medium | supplement | source_license |
| R05 | 超长时长 | low | confirm | 超过 60 分钟需确认 |

`check_rules` 返回 `risks`（规则编号/等级/原因）、`blocked`、`needs_supplement`；`save_draft` 在写入前再次跑审计，防止模型绕过检查直接保存。

## 六条红线的代码落点

| 红线 | 代码 |
| --- | --- |
| 只保存草稿 | `ALLOWED_DRAFT_STATUSES = {"draft", "draft_pending_confirmation"}`；无发布工具 |
| 硬性时间不改 | 提示词约束 + `query_slots` 给替代 + `save_draft` 拒绝冲突时段 + 待确认项 |
| 缺字段/高风险阻断 | `audit.evaluate` + `save_draft` 的 `material_incomplete` / `blocked_by_rules` |
| 保存失败如实返回 | `save_draft` 返回 `ok=false` / `error_type`；不捕获后改写成成功 |
| 同日幂等 | `idempotency_key = material_id:date`；重复返回已有 `draft_id` |
| 步数不足未完成 | `recursion_limit` + pre_model_hook + `task_status=incomplete` + `runner_note` |

## 框架版本与职责

| 依赖 | 版本 | 职责 |
| --- | --- | --- |
| langgraph | 1.2.19 | 图执行、流式 `updates`、`recursion_limit`、`remaining_steps` |
| langgraph-prebuilt | 1.1.1 | `create_react_agent`、`AgentState` |
| langchain-core | 1.7.3 | `AIMessage` / `ToolMessage` / `@tool` |
| langchain-openai | 1.7.3 | `ChatOpenAI`，指向业务空间兼容接口 |
| openai | 3.42.0 | 兼容接口客户端（传递依赖） |
| pytest | 9.2.0 | 测试 |

`create_react_agent` 在 langgraph 1.2.19 中已被标记 deprecated，官方建议 `langchain.agents.create_agent`；本项目按题目要求继续使用预构建 ReAct Agent，测试中会出现一条 warning，不影响功能。

## 已知偏差汇总

1. 模型名 `qwen3.8-max-0902` 替代 `qwen-plus`，接入用 ChatOpenAI 替代 ChatTongyi（用户确认）。
2. `trace.py` 未独立拆分，记录逻辑在 `agent.py`。
3. `SchedulingState` 的业务字段未在运行中回写，trace 由事件和 store 反推。
4. 步数上限触发时，框架最终输出为英文；中文未完成摘要由 `runner_note` 提供。
