# MewCode Agent Loop Tasks

> 每个任务是一个 2–5 分钟的聚焦工作单元。开发阶段按任务先补或调整对应测试，确认预期失败后完成最小实现，再运行所列验证。四份文档全部批准前不得执行这些实现任务。

## 文件清单

### 新建生产文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `mewcode/agent/__init__.py` | Agent 公共入口，只导出 Session、Run、计划快照与公共事件 |
| 新建 | `mewcode/agent/types.py` | 运行模式、阶段、停止原因、请求与计划类型 |
| 新建 | `mewcode/agent/events.py` | 不可变 Agent 事件及事件联合类型 |
| 新建 | `mewcode/agent/control.py` | 有界事件通道、序号、确认 Broker、取消与唯一终止 |
| 新建 | `mewcode/agent/collector.py` | 双路响应收集、原始工具调用与完整性检查 |
| 新建 | `mewcode/agent/scheduler.py` | 调用解析、保序批次、并发调度与有序反馈 |
| 新建 | `mewcode/agent/run.py` | 单次 `AgentRun` 和 ReAct 循环 |
| 新建 | `mewcode/agent/session.py` | `AgentSession`、命令解析、历史与计划状态 |
| 新建 | `mewcode/cancellation.py` | 协议中立 `CancellationToken` |
| 新建 | `mewcode/messages.py` | 协议中立的用户、助手和工具结果消息 |
| 新建 | `mewcode/tui/presentation.py` | TUI 活动状态、安全错误模型及事件到界面状态映射 |

### 修改生产文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `mewcode/providers/base.py` | 异步 Provider 协议、统一事件和 `TokenUsage` |
| 修改 | `mewcode/providers/sse.py` | 异步逐行 SSE 解析 |
| 修改 | `mewcode/providers/openai.py` | AsyncClient、instructions、多调用、usage、取消与关闭 |
| 修改 | `mewcode/providers/anthropic.py` | AsyncClient、system、多调用、usage、取消与关闭 |
| 修改 | `mewcode/providers/__init__.py` | 更新工厂和公共导出 |
| 修改 | `mewcode/tools/base.py` | 调用/反馈类型、静态策略、作用域、取消上下文与异步协议 |
| 修改 | `mewcode/tools/registry.py` | Descriptor 校验、保守默认和作用域视图 |
| 修改 | `mewcode/tools/executor.py` | 异步执行、确认函数、取消、超时、安全展示和结果限制 |
| 修改 | `mewcode/tools/workspace.py` | 可取消遍历和最窄异步文件系统边界 |
| 修改 | `mewcode/tools/file_tools.py` | 三个文件工具异步化并保持指纹与原子替换 |
| 修改 | `mewcode/tools/search_tools.py` | 查找和搜索异步化、可取消化 |
| 修改 | `mewcode/tools/command.py` | 异步子进程、超时与进程组清理 |
| 修改 | `mewcode/tools/defaults.py` | 注册六个工具的固定 Access/Execution 策略 |
| 修改 | `mewcode/tools/__init__.py` | 更新工具公共导出 |
| 修改 | `mewcode/tui/app.py` | 异步 Worker 直接消费 `AgentRun`，移除线程桥 |
| 修改 | `mewcode/tui/plain.py` | 异步输入、统一事件渲染、确认与取消 |
| 修改 | `mewcode/tui/widgets/chrome.py` | 使用新的 `ActivityState` 和进度状态 |
| 修改 | `mewcode/tui/widgets/conversation.py` | 接收安全 Agent 工具事件和错误展示模型 |
| 修改 | `mewcode/tui/__init__.py` | 移除旧交互导出并导出新界面入口 |
| 修改 | `mewcode/cli.py` | `async_main`、依赖装配和 Session 单一关闭 |
| 修改 | `README.md` | Agent Loop、停止条件、`/plan`、`/do` 与确认边界 |

### 删除生产文件

| 操作 | 文件 | 替代者 |
|---|---|---|
| 删除 | `mewcode/runtime.py` | `mewcode/agent/session.py` 与 `run.py` |
| 删除 | `mewcode/turns.py` | `mewcode/cancellation.py` 与 `agent/events.py` |
| 删除 | `mewcode/tui/interaction.py` | `AgentRun` 事件流与确认控制 |
| 删除 | `mewcode/tui/events.py` | `agent/events.py` 与 `tui/presentation.py` |

### 测试文件

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `tests/test_agent_events.py` | 事件不可变性、身份、序号和安全字段 |
| 新建 | `tests/test_agent_control.py` | 背压、单消费者、确认、取消和唯一终止 |
| 新建 | `tests/test_agent_collector.py` | 文本双路、工具增量、usage 与流完整性 |
| 新建 | `tests/test_agent_scheduler.py` | 解析、批次、并发、屏障、保序和未知判断 |
| 新建 | `tests/test_agent_run.py` | 循环、停止条件、历史事务、取消和 Token 累计 |
| 新建 | `tests/test_agent_session.py` | 命令解析、单运行约束和计划生命周期 |
| 修改 | `tests/test_providers.py` | 消息迁移、双 Provider 异步协议、多调用和 usage |
| 修改 | `tests/test_sse.py` | 异步 SSE、错误与取消 |
| 修改 | `tests/test_tool_registry.py` | 静态策略、约束、Descriptor 和作用域 |
| 修改 | `tests/test_tool_executor.py` | 异步确认、取消、超时、脱敏与错误转换 |
| 修改 | `tests/test_workspace.py` | 可取消异步遍历回归 |
| 修改 | `tests/test_file_tools.py` | 三个异步文件工具及取消安全 |
| 修改 | `tests/test_search_tools.py` | 并发安全读工具与取消 |
| 修改 | `tests/test_command_tool.py` | 异步子进程、超时和取消 |
| 修改 | `tests/test_tui_widgets.py` | 新展示模型和 Agent 安全事件适配 |
| 修改 | `tests/test_tui_app.py` | Textual 异步事件消费、确认、取消与恢复 |
| 修改 | `tests/test_tui_plain.py` | 纯文本异步消费、命令、确认与停止原因 |
| 修改 | `tests/test_cli.py` | `async_main`、两种终端模式和统一关闭 |
| 删除 | `tests/test_runtime.py` | 场景迁入 `test_agent_run.py` 与 `test_agent_session.py` |
| 删除 | `tests/test_turns.py` | 场景迁入 `test_agent_control.py` |
| 删除 | `tests/test_tui_interaction.py` | 场景迁入 Agent 事件、控制和两个 TUI 测试 |
| 按需修改 | `tests/__snapshots__/test_tui_app/*.raw` | 只接受轮次、停止原因或新命令带来的必要差异 |

`mewcode/config.py`、`config.yaml.example`、`pyproject.toml`、`uv.lock`、`mewcode/tui/metadata.py`、`mewcode/tui/mode.py`、`mewcode/tui/widgets/composer.py` 和 `mewcode/tui/widgets/confirmation.py` 不修改；`tests/test_config.py`、`tests/test_tui_metadata.py` 和 `tests/test_tui_mode.py` 保留为回归测试。

## T1：迁出协议中立会话消息

**文件：** `mewcode/messages.py`、`mewcode/providers/base.py`、`tests/test_providers.py`
**依赖：** 无

**步骤：**
1. 调整基础类型测试，覆盖 `UserMessage`、`AssistantMessage`、`ToolResultsMessage` 的不可变字段和隐藏 `provider_state`。
2. 将三种消息及 `ConversationMessage` 从 Provider 模块迁入 `mewcode/messages.py`。
3. 暂时从 Provider 基础模块重用新类型，保持当前序列化测试可收集。

**验证：** `uv run pytest tests/test_providers.py -k "base_types or message"`，期望消息类型测试通过。

## T2：实现协议中立取消令牌

**文件：** `mewcode/cancellation.py`、`tests/test_agent_control.py`
**依赖：** 无

**步骤：**
1. 测试初始未取消、幂等 `cancel()`、`is_cancelled` 和 `wait_cancelled()`。
2. 实现 `CancellationToken`，使 `raise_if_cancelled()` 抛出标准 `asyncio.CancelledError`。
3. 测试多个等待者在取消后全部释放，且令牌不依赖 Provider、工具或 TUI。

**验证：** `uv run pytest tests/test_agent_control.py -k cancellation_token`，期望全部通过。

## T3：定义工具调用、作用域与执行策略

**文件：** `mewcode/tools/base.py`、`mewcode/providers/base.py`、`tests/test_tool_registry.py`
**依赖：** T1、T2

**步骤：**
1. 测试 `ToolCall`、`ToolFeedback`、`ToolAccess`、`ToolExecutionPolicy`、`ToolScope`、`ToolDescriptor` 和 `ToolPresentation` 的稳定字段。
2. 将调用与反馈类型从 Provider 基础模块迁入工具基础模块，保留 `ToolResult` 的模型负载格式。
3. 给 `ToolContext` 加入取消令牌，并把 `Tool.prepare/execute` 协议改成异步；未声明静态策略的兼容行为留给注册中心。

**验证：** `uv run pytest tests/test_tool_registry.py -k "base or policy or scope"`，期望全部通过。

## T4：定义异步 Provider 事件与 Token 用量

**文件：** `mewcode/providers/base.py`、`tests/test_providers.py`
**依赖：** T1–T3

**步骤：**
1. 测试 `ProviderTextDelta`、`ProviderToolCallDelta`、`ProviderResponseCompleted` 和三维可空 `TokenUsage`。
2. 将 `LLMProvider.stream_response()` 改为返回异步事件迭代器，并加入关键字参数 `instructions`、`cancellation`。
3. 增加 `aclose()` 协议，确保 Provider 状态不进入 repr，缺失 usage 明确为三个 `None`。

**验证：** `uv run pytest tests/test_providers.py -k "base_types or token_usage or protocol"`，期望全部通过。

## T5：定义 Agent 运行与计划类型

**文件：** `mewcode/agent/types.py`、`tests/test_agent_session.py`
**依赖：** T3

**步骤：**
1. 测试 `RunMode`、`RunPhase`、`StopReason` 和 `PlanStatus` 的稳定字符串值。
2. 实现不可变 `AgentRequest` 与 `StoredPlan`，包括工具作用域和可选源计划 ID。
3. 测试计划记录不暴露可变字段，三种运行请求可精确区分。

**验证：** `uv run pytest tests/test_agent_session.py -k "types or request or stored_plan"`，期望全部通过。

## T6：定义统一 Agent 事件契约

**文件：** `mewcode/agent/events.py`、`tests/test_agent_events.py`
**依赖：** T3–T5

**步骤：**
1. 为 `EventContext`、开始、进度、文本、工具开始/结束、确认、用量和终止事件编写不可变性测试。
2. 实现 `AgentEvent` 联合类型；工具事件只携带安全摘要、状态、耗时、错误和截断信息，不携带完整结果。
3. 测试相同调用事件可用 `run_id`、轮次、批次、位置和 `call_id` 稳定关联，`RunStopped` 携带机器码与安全说明。

**验证：** `uv run pytest tests/test_agent_events.py`，期望全部通过。

## T7：让注册中心保存静态 Descriptor

**文件：** `mewcode/tools/registry.py`、`tests/test_tool_registry.py`
**依赖：** T3

**步骤：**
1. 测试注册后 `get()` 返回工具，`descriptor()` 返回定义、访问属性、执行策略与确认属性。
2. 对缺少声明的测试工具应用 `MUTATING + SERIAL` 保守默认。
3. 保留空名、重名和 JSON Schema 校验，并拒绝 `MUTATING` 或需确认却声明 `PARALLEL_SAFE` 的危险组合。

**验证：** `uv run pytest tests/test_tool_registry.py -k "descriptor or default_policy or dangerous_policy or schema"`，期望全部通过。

## T8：实现按作用域过滤工具定义

**文件：** `mewcode/tools/registry.py`、`tests/test_tool_registry.py`
**依赖：** T7

**步骤：**
1. 测试 `definitions("all")` 保持完整注册顺序。
2. 测试 `definitions("read_only")` 只返回 `READ_ONLY` 工具且不泄露内部 Descriptor。
3. 确认空注册中心和保守默认工具在只读作用域下行为稳定。

**验证：** `uv run pytest tests/test_tool_registry.py -k "definitions or read_only_scope"`，期望全部通过。

## T9：集中生成安全工具展示数据

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T3、T7

**步骤：**
1. 测试 `presentation()` 生成长度受限的工具名与参数摘要，并递归脱敏 API key。
2. 测试 `sanitize_preview()` 对标题、详情和嵌套敏感文本脱敏但不改变确认语义。
3. 从执行器移除开始/结束 UI 通知职责，使 Agent 只能取得安全 `ToolPresentation`。

**验证：** `uv run pytest tests/test_tool_executor.py -k "presentation or preview or redaction"`，期望全部通过。

## T10：异步执行未知工具与参数校验

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T2、T3、T7、T9

**步骤：**
1. 将记录型 fake 工具改为异步，测试未知工具返回 `unknown_tool`。
2. 测试 JSON Schema 缺字段、类型错误和额外字段返回 `invalid_arguments`，且不调用 `prepare()`。
3. 实现 `ToolExecutor.execute(call, cancellation, confirm)` 的异步查找、取消前置检查和 Schema 校验。

**验证：** `uv run pytest tests/test_tool_executor.py -k "unknown or arguments"`，期望全部通过。

## T11：异步执行准备、确认与拒绝

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T10

**步骤：**
1. 测试无需确认的工具按“prepare → execute”运行。
2. 测试副作用工具按“prepare → 脱敏预览 → await confirm → execute”运行，每次调用独立确认。
3. 测试拒绝返回结构化 `rejected/user_rejected`，不调用 `execute()`，并删除 `ToolInteraction`/`NullToolInteraction` 路径。

**验证：** `uv run pytest tests/test_tool_executor.py -k "confirmation or rejected or no_confirmation"`，期望全部通过。

## T12：实现异步超时、错误转换与取消传播

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T2、T11

**步骤：**
1. 用可控异步阻塞工具测试普通工具受 `asyncio.timeout(30)` 限制，命令工具继续管理自己的超时。
2. 测试输入错误、`ToolFailure` 和意外异常转换为结构化结果且经过脱敏。
3. 测试 `CancelledError` 原样传播，不被包装成工具失败，也不继续确认或执行。

**验证：** `uv run pytest tests/test_tool_executor.py -k "timeout or exception or cancellation"`，期望全部通过。

## T13：保留计时、截断与完整反馈

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T12

**步骤：**
1. 使用注入单调时钟测试 `duration_ms`，不得依赖真实等待。
2. 回归文本、路径、匹配和命令结果的统一截断及 `TruncationInfo`。
3. 确认完整 `ToolResult` 只作为模型反馈返回，面向事件的展示由 `presentation()` 和安全字段构造。

**验证：** `uv run pytest tests/test_tool_executor.py`，期望全部通过。

## T14：实现可取消的异步工作区遍历

**文件：** `mewcode/tools/workspace.py`、`tests/test_workspace.py`
**依赖：** T2、T3

**步骤：**
1. 保留现有路径解析、符号链接逃逸和 `.gitignore` 回归测试。
2. 将遍历改为可异步消费的稳定有序接口，只在最窄目录读取处使用 `asyncio.to_thread`。
3. 测试目录之间检查 Deadline 与取消令牌，取消后不再读取或产出路径。

**验证：** `uv run pytest tests/test_workspace.py`，期望全部通过。

## T15：异步化读取文件工具

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T13、T14

**步骤：**
1. 将 `ReadFileTool.prepare/execute` 测试改为 await，并保持全部、行范围、UTF-8、边界和截断行为。
2. 只在线程边界执行阻塞文件读取，分块之间检查 Deadline 与取消。
3. 声明 `READ_ONLY + PARALLEL_SAFE`，验证并发调用不会共享可变状态。

**验证：** `uv run pytest tests/test_file_tools.py -k read_file`，期望全部通过。

## T16：异步化写文件准备与冲突校验

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T13、T14

**步骤：**
1. 将 `WriteFileTool.prepare()` 改为异步，回归新建/覆盖 diff、原文件指纹和“准备阶段无副作用”。
2. 保持执行前重新解析工作区路径并比较指纹，文件变化时返回冲突错误。
3. 声明 `MUTATING + SERIAL` 且需要确认，测试准备期间取消不创建文件。

**验证：** `uv run pytest tests/test_file_tools.py -k "write_file and (prepare or conflict or cancel)"`，期望全部通过。

## T17：保护写文件原子替换临界区

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T2、T16

**步骤：**
1. 将临时文件写入和最终替换放入最窄异步线程边界。
2. 用短 `shield` 保护原子替换，临界区完成后传播已到达的取消。
3. 测试取消结果只能是旧文件或完整新文件，不出现半写内容，也不声称自动回滚。

**验证：** `uv run pytest tests/test_file_tools.py -k "write_file and (atomic or cancellation)"`，期望全部通过。

## T18：异步化精确编辑工具

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T13、T14、T17

**步骤：**
1. 将 `EditFileTool.prepare/execute` 改为异步，保留唯一匹配、预览、指纹和路径重检。
2. 复用受保护原子替换，声明 `MUTATING + SERIAL` 且需要确认。
3. 测试准备、拒绝、冲突和取消均不产生残缺编辑。

**验证：** `uv run pytest tests/test_file_tools.py -k edit_file`，期望全部通过。

## T19：异步化文件查找工具

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T13、T14

**步骤：**
1. 将 `GlobFilesTool` 测试和实现改为 await，保持 glob 校验、忽略规则和稳定排序。
2. 使用异步工作区遍历，在路径之间传播取消与 Deadline。
3. 声明 `READ_ONLY + PARALLEL_SAFE`，测试两个查找调用可重叠且结果互不污染。

**验证：** `uv run pytest tests/test_search_tools.py -k glob_files`，期望全部通过。

## T20：异步化内容搜索工具

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T13、T14

**步骤：**
1. 将 `SearchCodeTool` 测试和实现改为 await，保留 literal/regex、二进制和编码跳过统计。
2. 在文件读取和逐行匹配之间检查取消与 Deadline，阻塞读取进入最窄线程边界。
3. 声明 `READ_ONLY + PARALLEL_SAFE`，验证取消后不再追加匹配。

**验证：** `uv run pytest tests/test_search_tools.py -k search_code`，期望全部通过。

## T21：使用异步子进程执行命令

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T2、T13、T14

**步骤：**
1. 将命令工具 fake 进程和测试改为异步，保留 shell、工作目录、stdout/stderr、退出码和 1–300 秒参数语义。
2. 使用 `asyncio.create_subprocess_shell` 创建独立进程组并异步等待输出。
3. 声明 `MUTATING + SERIAL`、需要确认且自行管理超时。

**验证：** `uv run pytest tests/test_command_tool.py -k "success or failure or working_directory"`，期望全部通过。

## T22：终止超时或取消的命令进程组

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T21

**步骤：**
1. 测试超时后终止整个进程组、收集剩余输出并返回结构化 `timeout`。
2. 测试取消时先清理子进程/进程组再原样传播 `CancelledError`。
3. 覆盖 POSIX 主路径和可注入进程替身，不用真实 sleep 判断完成。

**验证：** `uv run pytest tests/test_command_tool.py -k "timeout or cancellation or process_group"`，期望全部通过。

## T23：固定六个内置工具的策略并更新导出

**文件：** `mewcode/tools/defaults.py`、`mewcode/tools/__init__.py`、`tests/test_tool_registry.py`
**依赖：** T8、T15、T17–T22

**步骤：**
1. 测试读取、查找、搜索为 `READ_ONLY + PARALLEL_SAFE`。
2. 测试写入、编辑、命令为 `MUTATING + SERIAL` 且逐次确认。
3. 更新默认注册顺序和工具包公共导出，不改变六个工具的名称、参数或结果结构。

**验证：** `uv run pytest tests/test_tool_registry.py -k "default_registry or builtin_policy"`，期望全部通过。

## T24：将 SSE 解析器改为异步迭代

**文件：** `mewcode/providers/sse.py`、`tests/test_sse.py`
**依赖：** T2、T4

**步骤：**
1. 将响应替身改为 `aiter_lines()`，用 `async for` 测试 event、单/多行 data、注释、空行和流末尾刷新。
2. 将 `iter_sse_events()` 实现为异步生成器，保持 `[DONE]` 结束语义。
3. 确认每个产出仍是 JSON 对象 `SSEEvent`，不理解任何 Provider 业务事件。

**验证：** `uv run pytest tests/test_sse.py -k "parses or multiline or comments or done"`，期望全部通过。

## T25：处理异步 SSE 错误与取消

**文件：** `mewcode/providers/sse.py`、`tests/test_sse.py`
**依赖：** T24

**步骤：**
1. 测试无效 JSON、非对象 JSON 和异步读取错误转换为安全 `ProviderError`。
2. 测试取消异步迭代时 `CancelledError` 原样传播，不包装为读取错误。
3. 验证响应上下文退出后不再产出迟到事件。

**验证：** `uv run pytest tests/test_sse.py -k "invalid or error or cancellation"`，期望全部通过。

## T26：建立 OpenAI 异步请求与客户端所有权

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T4、T24

**步骤：**
1. 用异步 HTTP 替身测试 Responses 请求包含 model、完整 history、tools、`stream=true` 和每轮固定 `instructions`。
2. 将实现改为 `httpx.AsyncClient` 与异步 stream 上下文，取消前后都检查令牌。
3. 记录客户端所有权：内部创建的客户端由 `aclose()` 关闭，注入客户端不关闭。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (request or instructions or client_ownership)"`，期望全部通过。

## T27：解析 OpenAI 文本、多工具增量与完成事件

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T25、T26

**步骤：**
1. 测试文本片段映射为 `ProviderTextDelta`。
2. 测试多个函数调用按槽位分别产生 ID、名称和参数增量，不互相拼接。
3. 测试完整响应恰好产生一个位于末尾的 `ProviderResponseCompleted`，重复或缺失完成事件报协议错误。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (text_delta or tool_delta or completed)"`，期望全部通过。

## T28：归一化 OpenAI Token 用量

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T27

**步骤：**
1. 测试完成事件中的 input、output、total 三个非负整数逐项映射。
2. 测试缺失、布尔值、负数或错误类型逐项变成 `None`。
3. 确认不从输入和输出自行计算缺失总数，原生其他细分不进入 Agent 事件。

**验证：** `uv run pytest tests/test_providers.py -k "openai and usage"`，期望全部通过。

## T29：完成 OpenAI 历史、取消、关闭和错误回归

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T1、T23、T28

**步骤：**
1. 回归多轮助手工具调用与多个 `ToolFeedback` 的 Responses 历史序列化。
2. 测试请求前取消、流中取消和 `aclose()` 都及时关闭自有资源且不吞取消。
3. 测试 HTTP、SSE 和协议错误脱敏 API key，并保留 base URL 排错提示。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (history or cancellation or close or error)"`，期望全部通过。

## T30：建立 Anthropic 异步请求与客户端所有权

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T4、T24

**步骤：**
1. 用异步 HTTP 替身测试 Messages 请求包含 model、完整 history、tools、thinking、`stream=true` 和每轮固定 `system`。
2. 将实现改为 `httpx.AsyncClient` 与异步 stream 上下文，取消前后检查令牌。
3. 与 OpenAI 一致实现自有客户端关闭、注入客户端不关闭。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (request or system or client_ownership)"`，期望全部通过。

## T31：解析 Anthropic 内容块与多工具增量

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T25、T30

**步骤：**
1. 测试文本、thinking 和 signature 分别累积，只有文本进入 `ProviderTextDelta`。
2. 测试多个 `tool_use` 块按 index 保持独立 ID、名称和 `input_json_delta`。
3. 保留完整内容块作为不透明 Provider 状态，Agent 不解析 thinking 或签名。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (content_block or tool_delta or thinking)"`，期望全部通过。

## T32：归一化 Anthropic 用量并完成消息

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T31

**步骤：**
1. 测试从 message start/delta 中取得协议提供的输入和输出用量。
2. 在 `message_stop` 产生唯一末尾 `ProviderResponseCompleted`，携带完整块与用量。
3. 测试未提供统一总数时 `total_tokens is None`，重复或缺少 stop 报协议错误。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (usage or completed or message_stop)"`，期望全部通过。

## T33：完成 Anthropic 历史、取消、关闭和错误回归

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T1、T23、T32

**步骤：**
1. 回归相邻用户内容合并、多轮助手工具块和多个工具结果的 Messages 历史序列化。
2. 测试请求前取消、流中取消和 `aclose()` 的资源清理与取消传播。
3. 测试 API error、HTTP、SSE 和协议错误全部脱敏 API key，thinking 禁用行为不变。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (history or cancellation or close or error)"`，期望全部通过。

## T34：更新 Provider 工厂与公共导出

**文件：** `mewcode/providers/__init__.py`、`tests/test_providers.py`
**依赖：** T29、T33

**步骤：**
1. 更新 `create_provider()` 和导出，公开异步 `LLMProvider`、Provider 事件与 `TokenUsage`。
2. 保持 OpenAI/Anthropic 配置选择和未知协议错误不变。
3. 运行双 Provider 测试，确认不再从 Provider 包导出会话消息或工具调用领域类型。

**验证：** `uv run pytest tests/test_providers.py`，期望全部通过。

## T35：实现文本实时转发与完整累积

**文件：** `mewcode/agent/collector.py`、`tests/test_agent_collector.py`
**依赖：** T4、T6

**步骤：**
1. 建立可控异步 Provider 流和记录型 `on_text`。
2. 实现 `ResponseCollector.collect()`：文本先追加内部列表，再 await `on_text`，流结束返回相同顺序的完整文本。
3. 测试慢 `on_text` 形成背压但不丢失、不重复、不乱序；首次 Provider 事件能让 Run 获知已进入接收阶段。

**验证：** `uv run pytest tests/test_agent_collector.py -k "text or backpressure or stream_started"`，期望全部通过。

## T36：收集多槽工具调用并生成稳定 ID

**文件：** `mewcode/agent/collector.py`、`tests/test_agent_collector.py`
**依赖：** T35

**步骤：**
1. 测试多个槽位的调用 ID、名称和参数增量独立拼接为 `RawToolCall` 并按 slot 排序。
2. 缺失 ID 时使用 run ID、iteration 和 slot 生成稳定替代值。
3. 测试重复非空调用 ID 和不稳定槽位触发协议完整性错误，不返回 `CollectedResponse`。

**验证：** `uv run pytest tests/test_agent_collector.py -k "tool_call or fallback_id or duplicate_id"`，期望全部通过。

## T37：验证完成信号并返回完整响应

**文件：** `mewcode/agent/collector.py`、`tests/test_agent_collector.py`
**依赖：** T36

**步骤：**
1. 只在恰好一个末尾 `ProviderResponseCompleted` 后返回文本、调用、usage 和不透明状态。
2. 测试缺少、重复或完成后仍有事件均报 Provider 协议错误。
3. 测试流错误或取消时已转发文本可见，但不返回完整响应，也不执行调用。

**验证：** `uv run pytest tests/test_agent_collector.py`，期望全部通过。

## T38：实现有界事件通道与全局序号

**文件：** `mewcode/agent/control.py`、`tests/test_agent_control.py`
**依赖：** T2、T6

**步骤：**
1. 建立容量 64 的异步队列，所有发布在同一锁内分配从 1 开始的 `sequence`。
2. 测试并发发布仍得到唯一递增序号，工具事件身份不因完成顺序错配。
3. 用阻塞消费者测试第 65 个待发布事件产生背压而非无界增长。

**验证：** `uv run pytest tests/test_agent_control.py -k "queue or sequence or backpressure"`，期望全部通过。

## T39：保证单消费者与唯一终止

**文件：** `mewcode/agent/control.py`、`tests/test_agent_control.py`
**依赖：** T38

**步骤：**
1. 测试同一 Run 只允许一个事件消费者。
2. 实现唯一 `RunStopped` 发布和通道关闭；重复终止或终止后普通发布被忽略。
3. 测试正常、错误和取消路径都恰好观察到一个终止事件。

**验证：** `uv run pytest tests/test_agent_control.py -k "single_consumer or terminal or late_event"`，期望全部通过。

## T40：实现异步确认 Broker

**文件：** `mewcode/agent/control.py`、`tests/test_agent_control.py`
**依赖：** T39

**步骤：**
1. 按注入 ID 工厂创建确认请求并保存未决 Future。
2. 测试正确 request ID 只能解析一次，未知、重复和过期 ID 返回 `False`。
3. 测试取消或关闭会拒绝并清空所有未决确认，且“运行取消”不伪装成用户拒绝。

**验证：** `uv run pytest tests/test_agent_control.py -k confirmation`，期望全部通过。

## T41：清理消费者提前退出和运行取消

**文件：** `mewcode/agent/control.py`、`tests/test_agent_control.py`
**依赖：** T2、T40

**步骤：**
1. 测试事件消费者提前 `aclose()` 会触发运行取消和确认清理。
2. 测试重复取消幂等，并可等待生产任务进入稳定关闭状态。
3. 确认后台任务、队列写入者和确认等待者均无孤立任务或未处理异常。

**验证：** `uv run pytest tests/test_agent_control.py -k "consumer_close or run_cancel or cleanup"`，期望全部通过。

## T42：独立解析每个原始工具调用

**文件：** `mewcode/agent/scheduler.py`、`tests/test_agent_scheduler.py`
**依赖：** T3、T7、T9

**步骤：**
1. 实现 `ToolScheduler.parse_calls()`，测试合法 JSON 对象转换为带原始位置的 `ScheduledToolCall`。
2. 测试无效 JSON、非对象参数各自产生 `preflight_error`，不阻止其他调用。
3. 测试未知工具使用 `SERIAL` 屏障并最终得到 `unknown_tool`，已知工具使用注册策略。

**验证：** `uv run pytest tests/test_agent_scheduler.py -k "parse or invalid or unknown"`，期望全部通过。

## T43：构造相邻并发批次与串行屏障

**文件：** `mewcode/agent/scheduler.py`、`tests/test_agent_scheduler.py`
**依赖：** T42

**步骤：**
1. 实现按 position 单次遍历的 `build_batches()`。
2. 测试连续 `PARALLEL_SAFE` 合并，每个 `SERIAL` 独占批次，空输入返回空批次。
3. 用“读 A、读 B、写 C、读 D”断言得到 `[A+B] → [C] → [D]`，不跨屏障重排。

**验证：** `uv run pytest tests/test_agent_scheduler.py -k batches`，期望全部通过。

## T44：并发执行批次并实时发布完成事件

**文件：** `mewcode/agent/scheduler.py`、`tests/test_agent_scheduler.py`
**依赖：** T13、T43

**步骤：**
1. 定义 Agent 内部 `ToolRunEvents` 协议；并发 `ToolBatch` 先按原始顺序调用 `events.started()`，再用 `asyncio.TaskGroup` 启动工具。
2. 使用 Event/Barrier 控制两个读工具重叠，并让完成顺序与模型顺序相反。
3. 测试 `events.finished()` 按实际完成时间发布，但结果槽按 position 保留原始顺序。

**验证：** `uv run pytest tests/test_agent_scheduler.py -k "parallel or completion_order"`，期望全部通过。

## T45：顺序执行串行批次与逐次确认

**文件：** `mewcode/agent/scheduler.py`、`tests/test_agent_scheduler.py`
**依赖：** T40、T44

**步骤：**
1. 测试串行调用只在前一批全部结束后开始，且绝不与同响应其他工具重叠。
2. 将 `events.confirm()` 作为执行器确认代理，每个副作用调用独立等待决定。
3. 测试批准与拒绝都形成自己的有序反馈，后续批次仍继续。

**验证：** `uv run pytest tests/test_agent_scheduler.py -k "serial or barrier or confirmation"`，期望全部通过。

## T46：完成取消、异常隔离与全未知判断

**文件：** `mewcode/agent/scheduler.py`、`tests/test_agent_scheduler.py`
**依赖：** T2、T45

**步骤：**
1. 测试普通工具错误已由执行器转换，不取消同批兄弟工具。
2. 测试用户取消会取消任务组和后续批次，调度器不返回残缺 `ToolScheduleOutcome`。
3. 仅当本轮所有反馈错误码都是 `unknown_tool` 时设置 `all_unknown=True`；混合已知、参数错或普通失败均为 `False`。

**验证：** `uv run pytest tests/test_agent_scheduler.py`，期望全部通过。

## T47：建立 AgentRun 生命周期与进度骨架

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T5、T6、T37、T41、T46

**步骤：**
1. 使用替代 Collector、Scheduler、会话提交回调和可注入 ID 工厂构造 `AgentRun`。
2. 后台启动运行任务，首先发布 `RunStarted` 和 `WAITING_MODEL`；首次收到 Provider 事件时发布 `STREAMING_MODEL`。
3. 实现异步迭代、`run_id`、`mode`、幂等 `cancel()`、确认解析和 `wait_closed()` 的公共骨架。

**验证：** `uv run pytest tests/test_agent_run.py -k "lifecycle or progress or public_control"`，期望全部通过。

## T48：实现无工具自然完成与历史提交

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T1、T47

**步骤：**
1. 测试首轮和后续任意轮无工具时只提交一次完整 `AssistantMessage`。
2. 发布 `RunStopped(COMPLETED)` 后结束，不再调用 Collector。
3. 测试 Provider 文本已流式显示但只有完整响应才能进入历史。

**验证：** `uv run pytest tests/test_agent_run.py -k "natural_completion or assistant_commit"`，期望全部通过。

## T49：实现多轮工具反馈循环与原子事务

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T3、T46、T48

**步骤：**
1. 有工具调用时发布 `EXECUTING_TOOLS`，等待完整 `ToolScheduleOutcome`。
2. 由 AgentRun 实现 `ToolRunEvents`：开始/结束映射为安全工具事件，确认映射为等待阶段、请求、解析和恢复执行阶段。
3. 将助手响应和有序 `ToolResultsMessage` 作为一个事务提交，再发布 `FEEDING_BACK` 并开始下一轮。
4. 用三轮不同工具脚本测试无需用户“继续”即可观察、调整并自然完成。

**验证：** `uv run pytest tests/test_agent_run.py -k "react_loop or tool_feedback or iteration_transaction"`，期望全部通过。

## T50：报告单轮与累计 Token 用量

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T4、T49

**步骤：**
1. 每个完整 Provider 响应后、工具判断前发布 `UsageReported`。
2. 使用三轮可控 usage 测试已知维度逐轮相加。
3. 任一轮某维度缺失后，该累计维度保持 `None`；不得将缺失当零或自行推导总数。

**验证：** `uv run pytest tests/test_agent_run.py -k usage`，期望全部通过。

## T51：实现十轮迭代上限

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T49

**步骤：**
1. 以可覆盖 `max_iterations` 测试连续工具响应达到上限。
2. 上限轮已开始的完整工具批次和事务照常完成，然后发布 `ITERATION_LIMIT`。
3. 断言没有下一轮 Provider 请求和额外总结请求；上限轮无工具时仍按自然完成。

**验证：** `uv run pytest tests/test_agent_run.py -k iteration_limit`，期望全部通过。

## T52：实现连续全未知工具停止

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T46、T49

**步骤：**
1. 每轮只根据 `ToolScheduleOutcome.all_unknown` 更新连续计数，同轮多个未知只计一次。
2. 连续第三轮完整反馈提交后发布 `UNKNOWN_TOOL_LIMIT`，不发起下一轮模型请求。
3. 测试已知工具、参数错误、普通失败或最终回答会重置/结束计数；与迭代上限同轮时未知停止优先。

**验证：** `uv run pytest tests/test_agent_run.py -k unknown_tool_limit`，期望全部通过。

## T53：转换 Provider 与 Agent 内部错误

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T37、T49

**步骤：**
1. Collector 的连接、SSE 或协议错误转换为唯一 `RunStopped(PROVIDER_ERROR)`，不自动重试。
2. 非预期调度/Agent 异常清理子任务并转换为脱敏 `INTERNAL_ERROR`。
3. 两种错误都丢弃当前未完整迭代，但保留此前已提交历史，并允许会话后续运行。

**验证：** `uv run pytest tests/test_agent_run.py -k "provider_error or internal_error or recovery"`，期望全部通过。

## T54：取消等待或接收中的模型响应

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T2、T37、T47

**步骤：**
1. 分别在首片段前和部分文本后取消，断言 Provider 流停止且无新片段。
2. 已显示部分文本不提交历史，运行发布唯一 `CANCELLED`。
3. 测试取消优先于同时到达的 Provider 错误，重复取消可安全等待关闭。

**验证：** `uv run pytest tests/test_agent_run.py -k "cancel_model or cancel_partial_text"`，期望全部通过。

## T55：取消工具、串行屏障与确认等待

**文件：** `mewcode/agent/run.py`、`tests/test_agent_run.py`
**依赖：** T41、T46、T54

**步骤：**
1. 在并发读工具、尚未开始的串行批次和确认等待中分别取消。
2. 断言可取消任务结束、后续工具/模型不启动、未决确认清理，并发布 `CANCELLED`。
3. 丢弃当前不完整助手+工具事务，保留此前迭代；已开始副作用只标记中断，不描述为已回滚。

**验证：** `uv run pytest tests/test_agent_run.py -k "cancel_tool or cancel_confirmation or transaction_on_cancel"`，期望全部通过。

## T56：实现精确斜杠命令解析

**文件：** `mewcode/agent/session.py`、`tests/test_agent_session.py`
**依赖：** T5、T8

**步骤：**
1. 测试普通文本为 `EXECUTE/all`，`/plan <任务>` 为 `PLAN/read_only`，有效 `/do` 为 `DO/all`，三种请求各自携带每轮固定模式指令。
2. 测试空 `/plan`、无计划/已完成计划的 `/do` 和带额外正文的 `/do` 返回稳定 `INVALID_REQUEST` 代码且零 Provider/工具调用。
3. 测试只识别输入开头的精确小写命令；`/PLAN`、`/DO` 和前导空白按普通文本处理。

**验证：** `uv run pytest tests/test_agent_session.py -k command_parser`，期望全部通过。

## T57：管理会话历史与单运行约束

**文件：** `mewcode/agent/session.py`、`tests/test_agent_session.py`
**依赖：** T47、T56

**步骤：**
1. `start()` 先提交用户消息并创建唯一 `AgentRun`，历史只通过 Session 的原子提交入口修改。
2. 活动 Run 未关闭时拒绝第二个请求；关闭后可开始新请求并看到此前完整历史。
3. 测试无效命令返回短生命周期 Run，只产生开始/终止事件且不污染历史。

**验证：** `uv run pytest tests/test_agent_session.py -k "history or single_run or invalid_request"`，期望全部通过。

## T58：保存、替换并保护规划结果

**文件：** `mewcode/agent/session.py`、`tests/test_agent_session.py`
**依赖：** T48、T57

**步骤：**
1. `/plan` 每轮只取得 `read_only` 定义；写入、修改和命令不可见，模型点名调用时按未知工具反馈。
2. 自然完成后将最终完整文本保存为带计划 ID 和源 Run ID 的新不可变 `READY` 计划。
3. 新计划只在成功时替换旧计划；取消、Provider 错误、未知工具停止或迭代上限保持旧计划，普通请求不改变计划。

**验证：** `uv run pytest tests/test_agent_session.py -k "plan_save or plan_replace or plan_preserve"`，期望全部通过。

## T59：实现 /do 计划生命周期

**文件：** `mewcode/agent/session.py`、`tests/test_agent_session.py`
**依赖：** T49、T58

**步骤：**
1. 有 `READY` 计划时，以计划内容、执行指令和全工具作用域创建 `DO` Run。
2. 自然完成后原子替换为 `COMPLETED`，再次 `/do` 直接返回 `plan_completed`。
3. 取消、流错误、未知工具停止或迭代上限保持 `READY` 可重试，期间普通请求不改变状态。

**验证：** `uv run pytest tests/test_agent_session.py -k do_lifecycle`，期望全部通过。

## T60：统一关闭活动运行与 Provider

**文件：** `mewcode/agent/session.py`、`tests/test_agent_session.py`
**依赖：** T34、T55、T57

**步骤：**
1. `AgentSession` 接管构造时传入的 Provider 所有权。
2. `close()` 幂等取消活动 Run、清理确认、等待后台任务并调用一次 `provider.aclose()`。
3. 测试关闭后拒绝新运行，不重复关闭 Provider，也不遗留任务；新建 Session 不恢复旧计划、用量或进度。

**验证：** `uv run pytest tests/test_agent_session.py -k close`，期望全部通过。

## T61：建立单一 Agent 公共入口

**文件：** `mewcode/agent/__init__.py`、`tests/test_agent_events.py`、`tests/test_agent_session.py`
**依赖：** T6、T47、T57–T60

**步骤：**
1. 只导出 `AgentSession`、`AgentRun`、计划快照、运行枚举和公共 Agent 事件。
2. 不导出 Collector、Scheduler、控制通道或 Provider/工具内部类型。
3. 用导入测试验证下层 Provider、工具、messages、cancellation 不反向导入 `agent`、`tui` 或 `cli`。

**验证：** `uv run pytest tests/test_agent_events.py tests/test_agent_session.py -k "public_api or import_direction"`，期望全部通过。

## T62：定义纯 TUI 展示状态与安全映射

**文件：** `mewcode/tui/presentation.py`、`tests/test_tui_widgets.py`
**依赖：** T5、T6

**步骤：**
1. 将 `ActivityState` 和安全错误展示模型从旧 `tui/events.py` 迁入展示模块。
2. 为运行阶段、停止原因、工具状态和用量定义无副作用映射，不保存完整 `ToolResult`。
3. 测试 API key、完整文件内容和内部异常不会进入展示对象。

**验证：** `uv run pytest tests/test_tui_widgets.py -k "activity or presentation or safe"`，期望全部通过。

## T63：让 Widget 接收新的展示模型

**文件：** `mewcode/tui/widgets/chrome.py`、`mewcode/tui/widgets/conversation.py`、`tests/test_tui_widgets.py`
**依赖：** T62

**步骤：**
1. Footer 和 ActivityIndicator 使用新 `ActivityState` 显示轮次、等待、流式、执行、确认、停止和错误状态。
2. `ToolCard` 与 `ErrorCard` 接收安全 Agent 事件/展示模型，保持调用身份、截断和错误提示。
3. 回归 ASCII、响应式布局、Markdown、提示历史和确认弹层，不改变视觉结构。

**验证：** `uv run pytest tests/test_tui_widgets.py`，期望全部通过。

## T64：异步渲染纯文本 Agent 事件

**文件：** `mewcode/tui/plain.py`、`tests/test_tui_plain.py`
**依赖：** T61–T63

**步骤：**
1. 将 `PlainChatApp` 改为异步消费当前 `AgentRun`，线性渲染文本、轮次/阶段、工具、用量和停止原因。
2. 保持非 TTY/ASCII 输出无控制序列，完整工具结果不打印。
3. 测试自然完成、Provider 错误、迭代上限、未知工具和无效命令后仍可继续输入。

**验证：** `uv run pytest tests/test_tui_plain.py -k "events or progress or stop_reason or recovery"`，期望全部通过。

## T65：实现纯文本异步输入、确认与取消

**文件：** `mewcode/tui/plain.py`、`tests/test_tui_plain.py`
**依赖：** T40、T60、T64

**步骤：**
1. 仅真实阻塞 `readline/write/flush` 在 I/O 适配边界使用线程；注入 StringIO 保持确定性。
2. 收到确认事件后显示脱敏预览，只把 `y/yes` 作为批准，通过当前 Run 解析 request ID。
3. 保留 EOF、`exit`、`quit` 和中断行为；取消时等待 Run 清理并恢复提示符。

**验证：** `uv run pytest tests/test_tui_plain.py -k "input or confirmation or cancellation or exit"`，期望全部通过。

## T66：让 Textual 异步 Worker 直接消费 AgentRun

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T61–T63

**步骤：**
1. `CyberpunkChatApp` 接收 `AgentSession`，提交后 await `start()` 并用无 `thread=True` 的异步 `@work` 消费事件。
2. 删除线程锁、`call_from_thread`、旧 Textual Agent Message 包装和 `TuiEventBridge`。
3. 在单次 UI 刷新周期内本地合并文本片段，测试快速片段无丢失且 Markdown 不高频全量重排。

**验证：** `uv run pytest tests/test_tui_app.py -k "normal_turn or rapid_chunks or async_worker"`，期望全部通过。

## T67：渲染全屏工具、进度、用量与确认

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T40、T66

**步骤：**
1. 按事件上下文将文本回复、并发工具卡、进度、usage 和停止原因关联到当前 Run。
2. 收到确认事件时显示现有 Modal，并将决定用 request ID 回传当前 Run。
3. 测试并发完成乱序不串卡、完整工具结果隐藏、多个副作用逐次确认。

**验证：** `uv run pytest tests/test_tui_app.py -k "tool or usage or confirmation or progress"`，期望全部通过。

## T68：完成全屏取消、退出、错误与恢复

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T41、T67

**步骤：**
1. Escape/Ctrl+C 取消当前 Run，关闭 Modal，将活动回复和工具卡标为 interrupted，并忽略迟到事件。
2. Unmount/Ctrl+D/`exit`/`quit` 通过 Session 关闭路径清理 Run、确认和 Provider。
3. 测试取消、Provider 错误和内部错误后 Composer 恢复且下一次运行可成功。

**验证：** `uv run pytest tests/test_tui_app.py -k "interrupt or exit or error or follow_up"`，期望全部通过。

## T69：完成 TUI 回归与必要快照更新

**文件：** `tests/test_tui_app.py`、`tests/test_tui_plain.py`、`tests/test_tui_widgets.py`、`tests/__snapshots__/test_tui_app/*.raw`
**依赖：** T65、T68

**步骤：**
1. 回归中英文、宽代码、窄屏、无颜色、ASCII、草稿保留和响应式 Footer。
2. 只在轮次、停止原因或 `/plan`/`/do` 可见信息需要时更新快照，逐项审查差异。
3. 确认界面替换不改变 Agent 的调用次数、历史和停止原因。

**验证：** `uv run pytest tests/test_tui_widgets.py tests/test_tui_plain.py tests/test_tui_app.py`，期望全部通过且快照差异均有对应行为理由。

## T70：实现 CLI 异步组合根与单一关闭

**文件：** `mewcode/cli.py`、`tests/test_cli.py`
**依赖：** T23、T34、T60、T65、T68

**步骤：**
1. 新增 `async_main()`，创建 Provider、默认注册中心、执行器、`AgentSession` 和终端界面。
2. 全屏 await Textual `run_async()`，纯文本 await 异步 `run()`。
3. `finally` 只调用 `session.close()`；测试 Provider 只关闭一次，CLI 不再创建界面专用工具交互对象。

**验证：** `uv run pytest tests/test_cli.py -k "async_main or wiring or close"`，期望全部通过。

## T71：保留同步 main、终端选择与启动错误

**文件：** `mewcode/cli.py`、`mewcode/tui/__init__.py`、`tests/test_cli.py`
**依赖：** T70

**步骤：**
1. 同步 `main()` 只负责启动一次异步主流程并转换启动期 `MewCodeError` 为退出码 1。
2. 保持工作区固定为当前目录、配置查找、纯文本/全屏检测和 Unicode 选择不变。
3. 更新 TUI 导出，移除 `PlainToolInteraction`、`TuiEventBridge`、`TuiToolInteraction`。

**验证：** `uv run pytest tests/test_cli.py tests/test_tui_mode.py tests/test_tui_metadata.py`，期望全部通过。

## T72：删除旧运行时、事件桥及迁移后的测试

**文件：** `mewcode/runtime.py`、`mewcode/turns.py`、`mewcode/tui/interaction.py`、`mewcode/tui/events.py`、`tests/test_runtime.py`、`tests/test_turns.py`、`tests/test_tui_interaction.py`
**依赖：** T61、T69、T71

**步骤：**
1. 确认旧测试场景已分别落入 Agent Run/Session/Control 与两个 TUI 测试后删除七个旧文件。
2. 更新所有内部导入，不保留兼容别名或转发模块。
3. 搜索 `ChatRuntime`、`TurnCancellation`、旧 TurnEvent、`ToolInteraction` 和 `TuiEventBridge`，期望生产代码与测试均无引用。

**验证：** `uv run python -m compileall mewcode tests && ! rg -n "ChatRuntime|TurnCancellation|TurnPhaseChanged|ToolInteraction|TuiEventBridge" mewcode tests`，期望编译通过且搜索无匹配。

## T73：更新 Agent Loop 用户文档

**文件：** `README.md`
**依赖：** T71

**步骤：**
1. 说明普通请求会自主循环以及模型完成、10 轮、取消、连续未知工具和流错误等停止条件。
2. 说明 `/plan <任务>` 只开放三种读工具、`/do` 执行最近 READY 计划及计划的重试/完成语义。
3. 明确写入、修改、命令仍逐次确认，并声明不含权限系统、上下文压缩、持久化或自动回滚。

**验证：** `rg -n "Agent Loop|/plan|/do|10|unknown|cancel|confirm|permission|context" README.md`，期望各项边界均有明确说明。

## T74：执行全量回归、编译与启动检查

**文件：** 本阶段全部创建、修改和删除文件
**依赖：** T1–T73

**步骤：**
1. 运行全量测试、Python 编译和锁文件检查，确认没有新增依赖。
2. 用空 HOME 分别运行模块入口和 console script，确认配置缺失仍安全退出 1 且无堆栈。
3. 检查 API key、空白错误、遗留导入、配置/锁文件差异和任务文件清单，再按批准的 `checklist.md` 执行验收。

**验证：**

```bash
uv run pytest
uv run python -m compileall mewcode tests
uv lock --check
env HOME="$(mktemp -d)" uv run python -m mewcode
env HOME="$(mktemp -d)" uv run mewcode
git diff --check
git status --short
```

期望测试、编译和锁检查通过；两个启动命令因缺少配置返回 1 且不泄露堆栈；diff 无空白错误；`pyproject.toml`、`uv.lock`、配置格式和查找顺序未变化。

## 执行顺序

```text
基础契约
T1 + T2 → T3 ─┬→ T4 → Provider 分支
              ├→ T5 → T6
              └→ T7 → T8

工具异步化
T7 + T9 → T10 → T11 → T12 → T13
T2 + T3 → T14
T13 + T14 ─┬→ T15
           ├→ T16 → T17 → T18
           ├→ T19
           ├→ T20
           └→ T21 → T22
T8 + T15 + T17-T22 → T23

双 Provider
T4 → T24 → T25
T25 + T26 → T27 → T28 → T29
T25 + T30 → T31 → T32 → T33
T29 + T33 → T34

Agent 内核
T4 + T6 → T35 → T36 → T37
T2 + T6 → T38 → T39 → T40 → T41
T3 + T7 + T9 → T42 → T43 → T44 → T45 → T46
T37 + T41 + T46 → T47 → T48 → T49
T49 ─┬→ T50
     ├→ T51
     ├→ T52
     └→ T53
T47 → T54 → T55

会话、界面与装配
T5 + T8 → T56 → T57 → T58 → T59
T34 + T55 + T57 → T60 → T61
T5 + T6 → T62 → T63
T61 + T63 ─┬→ T64 → T65
           └→ T66 → T67 → T68
T65 + T68 → T69
T23 + T34 + T60 + T65 + T68 → T70 → T71
T61 + T69 + T71 → T72
T71 → T73
T1-T73 → T74
```

同一分支严格按编号和显式依赖执行；多个分支只有在其依赖全部满足后才可并行。T72 必须最后删除旧入口，避免迁移过程中失去可运行基线。

## 覆盖检查

| Spec | 对应任务 |
|---|---|
| F1 | T47、T56–T61、T70–T71 |
| F2 | T35–T37、T42–T55 |
| F3 | T27、T31、T35–T37 |
| F4 | T25、T37、T53–T54 |
| F5 | T6、T38–T41、T47、T64、T66–T68 |
| F6 | T47、T62–T68 |
| F7 | T4、T28、T32、T37、T50、T64、T67 |
| F8 | T48 |
| F9 | T51 |
| F10 | T2、T12、T17、T22、T25、T29、T33、T41、T46、T54–T55、T65、T68 |
| F11 | T25、T29、T33、T37、T53 |
| F12 | T42、T46、T52 |
| F13 | T27、T31、T36、T42、T44 |
| F14 | T3、T7、T23、T43 |
| F15 | T43–T45 |
| F16 | T10–T13、T42–T49 |
| F17 | T11、T40、T45、T55、T65、T67 |
| F18 | T8、T23、T56、T58 |
| F19 | T58 |
| F20 | T56、T59 |
| F21 | T58–T59 |
| F22 | T1、T29、T33、T37、T48–T49、T53–T55、T57 |
| N1 | T2–T4、T10–T37、T38–T41、T44–T74 |
| N2 | T35、T38、T64、T66 |
| N3 | T6、T38–T39、T44–T47 |
| N4 | T6、T9、T38、T61–T71 |
| N5 | T2、T12、T17、T22、T25、T29、T33、T41、T46、T54–T55、T60、T65、T68 |
| N6 | T7、T23、T43–T46 |
| N7 | T1、T4、T24–T37 |
| N8 | T27–T34、T49、T74 |
| N9 | T37、T48–T49、T53–T55、T57 |
| N10 | T9、T12–T23、T29、T33、T42–T46、T62–T69 |
| N11 | T12、T46、T53、T59、T64–T68 |
| N12 | T6、T38–T39、T44、T47、T53 |
| N13 | T4、T28、T32、T50 |
| N14 | T2、T12、T22、T35–T60 及各任务的可控替代组件测试 |
| N15 | T15–T23、T29、T33、T63–T74 |
| N16 | T5、T56–T60、T74 |
| N17 | T51、T70–T71、T74 |
