# MewCode Tool System Tasks

> 每个任务是一个聚焦工作单元；先补对应测试，确认失败后完成最小实现，再运行所列验证。

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `mewcode/tools/__init__.py` | 导出工具系统公开接口 |
| 新建 | `mewcode/tools/base.py` | 工具定义、结果、截止时间、执行计划和工具协议 |
| 新建 | `mewcode/tools/registry.py` | 工具注册、Schema 检查和按名查找 |
| 新建 | `mewcode/tools/workspace.py` | 路径安全、忽略规则和安全遍历 |
| 新建 | `mewcode/tools/executor.py` | 参数校验、确认、超时、异常、截断、脱敏和状态通知 |
| 新建 | `mewcode/tools/file_tools.py` | `read_file`、`write_file`、`edit_file` |
| 新建 | `mewcode/tools/search_tools.py` | `glob_files`、`search_code` |
| 新建 | `mewcode/tools/command.py` | `run_command`、进程组和超时终止 |
| 新建 | `mewcode/tools/defaults.py` | 六个内置工具及默认限制 |
| 修改 | `mewcode/providers/base.py` | 统一消息、工具调用、流式事件和 Provider 接口 |
| 修改 | `mewcode/providers/openai.py` | OpenAI 工具协议适配 |
| 修改 | `mewcode/providers/anthropic.py` | Anthropic 工具协议适配 |
| 修改 | `mewcode/providers/__init__.py` | 保留工厂并导出统一类型 |
| 修改 | `mewcode/runtime.py` | 固定两阶段单工具状态机 |
| 修改 | `mewcode/tui.py` | 工具状态、预览和确认交互 |
| 修改 | `mewcode/cli.py` | 工具系统依赖装配 |
| 修改 | `mewcode/errors.py` | 工具内部异常类型 |
| 新建 | `tests/test_tool_registry.py` | 基础类型、注册和默认工具测试 |
| 新建 | `tests/test_workspace.py` | 路径、符号链接、忽略和遍历测试 |
| 新建 | `tests/test_file_tools.py` | 文件工具测试 |
| 新建 | `tests/test_search_tools.py` | 查找与内容搜索测试 |
| 新建 | `tests/test_command_tool.py` | 命令工具测试 |
| 新建 | `tests/test_tool_executor.py` | 执行器测试 |
| 修改 | `tests/test_providers.py` | 两种 Provider 的工具协议测试 |
| 修改 | `tests/test_runtime.py` | 单工具编排和额度限制测试 |
| 修改 | `tests/test_tui.py` | 工具交互和 CLI 装配测试 |
| 修改 | `pyproject.toml` | 增加工具系统依赖 |
| 修改 | `uv.lock` | 锁定新增依赖 |
| 修改 | `README.md` | 工具能力与安全边界说明 |

`config.yaml.example` 不修改，本阶段不增加配置字段。

## T1：增加并锁定依赖

**文件：** `pyproject.toml`、`uv.lock`
**依赖：** 无

**步骤：**
1. 在运行时依赖中加入 `jsonschema` 和 `pathspec`。
2. 运行 `uv sync --all-groups` 更新锁文件。
3. 导入两个包确认环境可用。

**验证：** `uv run python -c "import jsonschema, pathspec; print('tool deps ok')"`，期望输出 `tool deps ok`。

## T2：定义结构化工具结果

**文件：** `mewcode/tools/base.py`、`tests/test_tool_registry.py`
**依赖：** T1

**步骤：**
1. 测试成功、错误、拒绝、超时和截断结果的稳定字段。
2. 测试 `to_model_payload()` 可被 `json.dumps()` 序列化。
3. 实现 `JSONValue`、`ToolErrorInfo`、`TruncationInfo`、`ToolResult` 和状态字面量。

**验证：** `uv run pytest tests/test_tool_registry.py -k result`，期望全部通过。

## T3：定义工具执行基础类型

**文件：** `mewcode/tools/base.py`、`mewcode/errors.py`、`tests/test_tool_registry.py`
**依赖：** T2

**步骤：**
1. 测试 `ToolDefinition`、`ConfirmationPreview`、`PreparedToolAction`、`ToolContext` 和 `ToolOutputLimits` 的字段与不可变行为。
2. 实现单调时钟 `Deadline`，测试到期检查会抛出内部截止异常。
3. 定义 `Tool` 协议以及参数、路径、编码、冲突、截止时间内部异常。

**验证：** `uv run pytest tests/test_tool_registry.py -k "base or deadline"`，期望全部通过。

## T4：定义统一 Provider 类型

**文件：** `mewcode/providers/base.py`、`tests/test_providers.py`
**依赖：** T2

**步骤：**
1. 测试用户、助手、工具结果三种会话消息的字段。
2. 测试 `ToolCallDelta`、`ToolCall`、`ToolFeedback`、`TextDelta`、`ResponseCompleted` 的字段。
3. 用 `stream_response(history, tools)` 统一接口替换旧纯文本 Provider 协议。
4. 确保 `provider_state` 不出现在默认对象表示中。

**验证：** `uv run pytest tests/test_providers.py -k "base_types or provider_protocol"`，期望全部通过。

## T5：实现工具注册和查找

**文件：** `mewcode/tools/registry.py`、`tests/test_tool_registry.py`
**依赖：** T3

**步骤：**
1. 测试合法工具可按名称查找，定义保持注册顺序。
2. 测试空名称和重复名称被拒绝。
3. 实现 `register()`、`get()` 和 `definitions()`。

**验证：** `uv run pytest tests/test_tool_registry.py -k "register or lookup or duplicate"`，期望全部通过。

## T6：实现注册时 Schema 检查

**文件：** `mewcode/tools/registry.py`、`tests/test_tool_registry.py`
**依赖：** T5

**步骤：**
1. 测试无效 JSON Schema、非对象根 Schema 被拒绝。
2. 测试缺少 `additionalProperties: false` 的内置工具 Schema 被拒绝。
3. 使用 `jsonschema` 检查器实现注册时校验。

**验证：** `uv run pytest tests/test_tool_registry.py -k schema`，期望全部通过。

## T7：实现现有路径边界检查

**文件：** `mewcode/tools/workspace.py`、`tests/test_workspace.py`
**依赖：** T3

**步骤：**
1. 测试根目录在构造时解析并固定。
2. 测试普通相对文件可解析。
3. 测试绝对路径、含 `..` 路径和指向工作区外的符号链接被拒绝。
4. 实现只用于现有文件的安全解析入口。

**验证：** `uv run pytest tests/test_workspace.py -k existing_path`，期望全部通过。

## T8：实现新建目标路径检查

**文件：** `mewcode/tools/workspace.py`、`tests/test_workspace.py`
**依赖：** T7

**步骤：**
1. 测试父目录不存在的新文件路径可通过检查。
2. 测试已有父目录中的符号链接不能逃逸工作区。
3. 测试目标存在且是目录时被拒绝。
4. 实现创建目标的逐级父目录边界检查。

**验证：** `uv run pytest tests/test_workspace.py -k create_path`，期望全部通过。

## T9：实现忽略规则

**文件：** `mewcode/tools/workspace.py`、`tests/test_workspace.py`
**依赖：** T1、T7

**步骤：**
1. 测试 `.git` 始终忽略。
2. 测试 `.gitignore` 的文件、目录、通配和否定规则。
3. 测试显式路径解析不受忽略规则影响。
4. 使用 `pathspec` 实现相对路径忽略判断。

**验证：** `uv run pytest tests/test_workspace.py -k ignore`，期望全部通过。

## T10：实现安全文件遍历

**文件：** `mewcode/tools/workspace.py`、`tests/test_workspace.py`
**依赖：** T3、T8、T9

**步骤：**
1. 测试遍历只产出稳定排序的工作区相对文件路径。
2. 测试不跟随目录符号链接，也不产出忽略路径。
3. 测试遍历期间检查 Deadline 并可中止。
4. 实现可中断安全遍历接口。

**验证：** `uv run pytest tests/test_workspace.py -k walk`，期望全部通过。

## T11：实现执行器查找与参数校验

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T4、T6、T7

**步骤：**
1. 建立 fake Tool 和记录型 fake 交互端口。
2. 测试未知工具返回 `unknown_tool`。
3. 测试缺字段、错误类型和额外字段返回带参数位置的 `invalid_arguments`，且不调用 `prepare()`。
4. 实现工具查找和 `jsonschema` 调用参数校验。

**验证：** `uv run pytest tests/test_tool_executor.py -k "unknown or arguments"`，期望全部通过。

## T12：实现执行器确认流程

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T11

**步骤：**
1. 测试无需确认的工具在 `prepare()` 后直接执行。
2. 测试需确认工具按“准备、确认、执行”顺序运行。
3. 测试拒绝返回 `rejected` 且不调用 `execute()`。
4. 实现 `ToolInteraction` 与确认编排。

**验证：** `uv run pytest tests/test_tool_executor.py -k "confirm or rejected"`，期望全部通过。

## T13：实现执行器失败、计时和通知

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T12

**步骤：**
1. 测试普通工具使用固定 30 秒 Deadline，截止异常返回 `timeout`。
2. 测试内部异常返回结构化 `error`，不显示堆栈。
3. 测试开始与结束通知在成功和失败路径各调用一次。
4. 实现计时、异常转换和状态通知。

**验证：** `uv run pytest tests/test_tool_executor.py -k "timeout or exception or notification"`，期望全部通过。

## T14：实现执行器脱敏与截断

**文件：** `mewcode/tools/executor.py`、`tests/test_tool_executor.py`
**依赖：** T13

**步骤：**
1. 测试参数、结果和异常中的 API key 被脱敏。
2. 测试文本、路径和匹配集合超限时返回限定内容与 `TruncationInfo`。
3. 测试未超限结果保持原值且不带截断信息。
4. 实现递归脱敏和统一结果限制。

**验证：** `uv run pytest tests/test_tool_executor.py`，期望全部通过。

## T15：实现 UTF-8 文件读取

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T7、T14

**步骤：**
1. 测试工具定义及 `path`、可选 `start_line`、`line_count` 参数。
2. 测试读取全部或指定行范围，返回路径、内容、总行数和实际范围。
3. 测试明确路径读取被忽略文件仍成功。
4. 实现分块严格 UTF-8 读取并检查 Deadline。

**验证：** `uv run pytest tests/test_file_tools.py -k "read_file and success"`，期望全部通过。

## T16：补齐读取错误与截断

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T15

**步骤：**
1. 测试非法行范围、缺失文件、目录和路径逃逸返回结构化错误。
2. 测试二进制及无效 UTF-8 文件返回编码错误。
3. 测试大文件由执行器返回字符截断信息。
4. 补齐错误映射和读取元数据。

**验证：** `uv run pytest tests/test_file_tools.py -k read_file`，期望全部通过。

## T17：实现写文件准备与预览

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T8、T14

**步骤：**
1. 测试 Schema 只接受 `path`、`content`，并要求确认。
2. 测试新建与覆盖分别生成含目标路径的统一 diff。
3. 测试 `prepare()` 不创建目录或文件。
4. 实现原文件读取、指纹记录和预览生成。

**验证：** `uv run pytest tests/test_file_tools.py -k "write_file and prepare"`，期望全部通过。

## T18：实现安全原子写入

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T17

**步骤：**
1. 测试确认后自动创建父目录并新建文件。
2. 测试完整覆盖已有 UTF-8 文件。
3. 实现同目录临时文件、flush、同步、原子替换和失败清理。
4. 测试路径逃逸与无效目标不产生副作用。

**验证：** `uv run pytest tests/test_file_tools.py -k "write_file and execute"`，期望全部通过。

## T19：实现写入冲突检测

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T18

**步骤：**
1. 测试预览后原文件内容变化返回 `file_conflict`。
2. 测试预览后父目录被替换为逃逸符号链接时拒绝写入。
3. 测试冲突路径保留外部变化且清理临时文件。
4. 执行前重新校验路径与指纹。

**验证：** `uv run pytest tests/test_file_tools.py -k "write_file and conflict"`，期望全部通过。

## T20：实现改文件唯一匹配准备

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T17

**步骤：**
1. 测试 Schema 接受 `path`、`old_text`、`new_text`，拒绝空 `old_text`。
2. 测试一次匹配生成准确 diff 和原文件指纹。
3. 测试零匹配返回 `text_not_found`，多匹配返回 `text_not_unique`。
4. 实现唯一匹配检查和预览。

**验证：** `uv run pytest tests/test_file_tools.py -k "edit_file and prepare"`，期望全部通过。

## T21：实现改文件执行与冲突检查

**文件：** `mewcode/tools/file_tools.py`、`tests/test_file_tools.py`
**依赖：** T18、T20

**步骤：**
1. 测试确认后只替换唯一匹配位置。
2. 测试用户拒绝、零匹配和多匹配均保持文件不变。
3. 测试预览后文件变化返回 `file_conflict`。
4. 复用安全原子写入逻辑完成修改。

**验证：** `uv run pytest tests/test_file_tools.py -k edit_file`，期望全部通过。

## T22：实现按模式找文件

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T10、T14

**步骤：**
1. 测试 Schema 只接受工作区相对 `pattern`。
2. 测试递归模式、精确文件名和无匹配结果。
3. 测试 `.git` 与忽略项不出现，结果稳定排序。
4. 实现基于安全遍历的路径模式匹配。

**验证：** `uv run pytest tests/test_search_tools.py -k "glob_files and basic"`，期望全部通过。

## T23：补齐找文件错误与截断

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T22

**步骤：**
1. 测试绝对模式和含 `..` 模式被拒绝。
2. 测试超过 1,000 条路径时返回限定路径、原始数量和缩小范围提示。
3. 测试遍历超时转换为结构化超时结果。
4. 补齐模式验证和结果元数据。

**验证：** `uv run pytest tests/test_search_tools.py -k glob_files`，期望全部通过。

## T24：实现字面内容搜索

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T10、T14

**步骤：**
1. 测试 Schema 的 `query`、可选 `path_pattern`、`regex` 字段。
2. 测试默认字面搜索返回相对路径、1 基行号和匹配行。
3. 测试路径模式限制搜索范围。
4. 实现逐文件逐行搜索并检查 Deadline。

**验证：** `uv run pytest tests/test_search_tools.py -k "search_code and literal"`，期望全部通过。

## T25：实现正则搜索与文件跳过

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T24

**步骤：**
1. 测试正则搜索和无效正则错误。
2. 测试 `.git`、忽略文件、二进制及无效 UTF-8 文件被跳过。
3. 测试结果摘要报告跳过文件数量。
4. 实现正则编译和严格文本文件筛选。

**验证：** `uv run pytest tests/test_search_tools.py -k "search_code and (regex or skipped)"`，期望全部通过。

## T26：补齐搜索截断

**文件：** `mewcode/tools/search_tools.py`、`tests/test_search_tools.py`
**依赖：** T25

**步骤：**
1. 测试超过 500 条匹配时仍统计原始总量。
2. 测试只返回前 500 条稳定结果及缩小范围提示。
3. 补齐匹配计数和统一截断元数据。

**验证：** `uv run pytest tests/test_search_tools.py`，期望全部通过。

## T27：实现命令参数和确认预览

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T8、T14

**步骤：**
1. 测试 Schema 接受完整 `command` 与可选 `timeout_seconds`。
2. 测试空命令、非正数及超过 300 秒的超时被拒绝。
3. 测试预览原样展示命令且不启动进程。
4. 实现命令准备逻辑。

**验证：** `uv run pytest tests/test_command_tool.py -k prepare`，期望全部通过。

## T28：实现 shell 命令执行

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T27

**步骤：**
1. 测试工作目录固定为工作区根。
2. 测试管道、重定向和条件连接由当前 shell 执行。
3. 测试成功与非零退出返回退出码、stdout、stderr；非零状态为 `error`。
4. 实现可注入子进程启动器和严格 UTF-8 输出解码。

**验证：** `uv run pytest tests/test_command_tool.py -k "execute or exit_code"`，期望全部通过。

## T29：实现命令超时和进程组终止

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T28

**步骤：**
1. 测试默认 30 秒和调用参数指定超时被传入等待逻辑。
2. 测试超时终止整个进程组并返回 `timeout`。
3. 测试退出后不残留子进程。
4. 实现平台对应的独立进程组创建与终止。

**验证：** `uv run pytest tests/test_command_tool.py -k timeout`，期望全部通过且无残留进程。

## T30：补齐命令编码与输出截断

**文件：** `mewcode/tools/command.py`、`tests/test_command_tool.py`
**依赖：** T29

**步骤：**
1. 测试 stdout 或 stderr 非 UTF-8 时返回编码错误。
2. 测试两路输出各自超过 50,000 字符时独立截断并报告总量。
3. 补齐编码错误与双流截断元数据。

**验证：** `uv run pytest tests/test_command_tool.py`，期望全部通过。

## T31：注册并导出六个默认工具

**文件：** `mewcode/tools/defaults.py`、`mewcode/tools/__init__.py`、`tests/test_tool_registry.py`
**依赖：** T6、T16、T21、T23、T26、T30

**步骤：**
1. 测试默认注册中心恰好包含六个指定名称且顺序稳定。
2. 测试写入、修改、命令需要确认，读取与搜索无需确认。
3. 测试全部定义可 JSON 序列化且 Schema 禁止额外参数。
4. 实现默认限制、注册入口和最小公开导出。

**验证：** `uv run pytest tests/test_tool_registry.py -k defaults`，期望全部通过。

## T32：实现 OpenAI 工具定义与用户消息序列化

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T4、T31

**步骤：**
1. 测试统一工具定义转换为函数工具名称、描述和参数 Schema。
2. 测试用户消息转换为 Responses API 普通输入。
3. 测试空工具列表不会在第二次请求中暴露工具。
4. 实现请求构造辅助函数并保留现有模型、认证、URL 和流式字段。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (tools or user_message)"`，期望全部通过。

## T33：实现 OpenAI 助手状态与工具结果回灌

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T32

**步骤：**
1. 测试助手 `provider_state` 输出条目按原顺序回放。
2. 测试工具结果转换为含调用 ID 的函数结果条目。
3. 测试结构化结果使用稳定 JSON 序列化。
4. 实现历史序列化并保持密钥脱敏。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (history or feedback)"`，期望全部通过。

## T34：实现 OpenAI 文本流与完成状态

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T33

**步骤：**
1. 测试文本增量立即产生 `TextDelta`。
2. 测试完成事件产生唯一 `ResponseCompleted` 并保存完整输出状态。
3. 测试流缺少完成事件返回 `ProviderError`。
4. 实现 `stream_response()` 的文本与完成路径。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (text_delta or completed)"`，期望全部通过。

## T35：实现 OpenAI 工具调用增量

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T34

**步骤：**
1. 测试调用 ID、名称和 JSON 参数跨多个事件产生同一 slot 的 `ToolCallDelta`。
2. 测试两个工具调用保持不同 slot。
3. 测试错误事件和 HTTP 错误脱敏。
4. 完成工具调用事件映射并移除旧 `stream_chat()` 路径。

**验证：** `uv run pytest tests/test_providers.py -k "openai and (tool_delta or error)"`，期望全部通过。

## T36：实现 Anthropic 工具定义与用户消息序列化

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T4、T31

**步骤：**
1. 测试工具定义转换为名称、描述和 `input_schema`。
2. 测试用户消息转换为用户文本内容。
3. 测试空工具列表时不提供工具。
4. 实现请求构造并保留模型、认证、`max_tokens` 和 thinking 配置。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (tools or user_message or thinking)"`，期望全部通过。

## T37：实现 Anthropic 助手状态与工具结果回灌

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T36

**步骤：**
1. 测试助手 `provider_state` 转换为完整 assistant 内容块。
2. 测试工具结果转换为 user `tool_result` 内容块。
3. 测试工具结果与相邻用户内容按协议消息边界合并。
4. 实现历史序列化和稳定 JSON 工具结果。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (history or feedback)"`，期望全部通过。

## T38：实现 Anthropic 文本流与完成状态

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T37

**步骤：**
1. 测试 `text_delta` 产生 `TextDelta`，thinking/signature 不产生终端文本。
2. 测试消息完成产生唯一 `ResponseCompleted` 并保留完整内容块。
3. 测试缺少完成事件返回 `ProviderError`。
4. 实现 `stream_response()` 的文本、thinking 和完成路径。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (text_delta or completed)"`，期望全部通过。

## T39：实现 Anthropic 工具调用增量

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T38

**步骤：**
1. 测试 `tool_use` 开始事件产生调用 ID 与名称片段。
2. 测试多个 `input_json_delta` 按内容块 slot 产生参数片段。
3. 测试多个工具块保持不同 slot，错误事件和 HTTP 错误脱敏。
4. 完成工具调用映射并移除旧 `stream_chat()` 路径。

**验证：** `uv run pytest tests/test_providers.py -k "anthropic and (tool_delta or error)"`，期望全部通过。

## T40：实现运行时响应收集器

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T4、T35、T39

**步骤：**
1. 建立记录历史、工具定义和调用次数的 fake Provider。
2. 测试文本增量立即作为字符串产出。
3. 测试调用字段按 slot 拼接，并只在完成事件后解析 JSON 对象。
4. 实现内部响应收集器，不执行工具。

**验证：** `uv run pytest tests/test_runtime.py -k "collector or delta"`，期望全部通过。

## T41：实现普通文本轮次

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T40

**步骤：**
1. 测试无工具调用只请求 Provider 一次。
2. 测试用户消息和完整助手消息按顺序写入历史。
3. 测试流中途失败不写入助手消息，但保留用户消息。
4. 实现普通响应历史提交。

**验证：** `uv run pytest tests/test_runtime.py -k plain`，期望全部通过。

## T42：实现单工具执行与结果回灌

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T14、T31、T40

**步骤：**
1. 测试一个合法工具调用只执行一次。
2. 测试完整助手响应、工具结果消息按顺序写入历史。
3. 测试成功、错误、拒绝和超时结果都会触发第二次请求。
4. 实现单工具执行和回灌入口。

**验证：** `uv run pytest tests/test_runtime.py -k "single_tool or feedback"`，期望全部通过。

## T43：实现最终回答阶段

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T42

**步骤：**
1. 测试第二次请求收到空工具定义。
2. 测试最终文本继续流式产出并保存完整助手消息。
3. 测试总 Provider 调用次数恰好为二。
4. 实现固定第二阶段，不使用通用循环。

**验证：** `uv run pytest tests/test_runtime.py -k final_response`，期望全部通过。

## T44：实现参数错误回灌

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T40、T43

**步骤：**
1. 测试不完整 JSON、数组和标量参数不执行工具。
2. 测试返回关联调用 ID 的 `invalid_tool_arguments`。
3. 测试错误仍触发一次最终回答请求。
4. 实现解析失败结果构造。

**验证：** `uv run pytest tests/test_runtime.py -k invalid_arguments`，期望全部通过。

## T45：实现多工具全部拒绝

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T43

**步骤：**
1. 测试首次响应含多个 slot 时任何工具都不执行。
2. 测试每个调用获得关联自身 ID 的 `multiple_tool_calls` 错误。
3. 测试全部错误一次性回灌后请求最终回答。
4. 实现多调用拒绝分支。

**验证：** `uv run pytest tests/test_runtime.py -k multiple_tool_calls`，期望全部通过。

## T46：实现第二次工具调用额度限制

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T43

**步骤：**
1. 测试第二次响应出现工具调用时不执行、不发起第三次请求。
2. 测试通知交互端口“本轮工具额度已用完”。
3. 测试已流出文本可显示，但违规助手响应不写入历史。
4. 实现第二阶段防御性终止。

**验证：** `uv run pytest tests/test_runtime.py -k tool_budget`，期望全部通过。

## T47：验证违规轮次后的历史可继续

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T44-T46

**步骤：**
1. 测试参数错误、多工具和二次违规三种历史均无悬空协议消息。
2. 测试下一轮普通对话可使用此前完整历史继续。
3. 修正历史提交边界并统一只读 `history` 属性。

**验证：** `uv run pytest tests/test_runtime.py`，期望全部通过。

## T48：实现终端工具状态显示

**文件：** `mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T14、T47

**步骤：**
1. 测试开始状态显示工具名和经过筛选的关键参数。
2. 测试完成状态区分成功、错误、拒绝和超时。
3. 测试读取与搜索的完整结果不打印到终端。
4. 实现 `TerminalToolInteraction` 状态方法。

**验证：** `uv run pytest tests/test_tui.py -k tool_status`，期望全部通过。

## T49：实现终端确认与预览

**文件：** `mewcode/tui.py`、`tests/test_tui.py`
**依赖：** T48

**步骤：**
1. 测试命令确认显示完整命令，写入和修改显示路径与 diff。
2. 测试只有大小写不敏感的 `y`/`yes` 批准，其余输入和 EOF 拒绝。
3. 测试预览、状态和错误中的 API key 被脱敏。
4. 让终端交互与 `ChatApp` 共享输入输出流，保留原有聊天行为。

**验证：** `uv run pytest tests/test_tui.py -k "confirm or preview or tool_redaction"`，期望全部通过。

## T50：完成 CLI 工具装配

**文件：** `mewcode/cli.py`、`mewcode/providers/__init__.py`、`tests/test_tui.py`
**依赖：** T31、T35、T39、T47、T49

**步骤：**
1. 测试 `main()` 调用时当前目录成为固定工作区根。
2. 测试六工具注册中心、执行器、交互端口、Provider、运行时和 TUI 被正确连接。
3. 测试 OpenAI 与 Anthropic 使用相同装配路径，配置失败不创建工具副作用。
4. 更新工厂导出并完成 CLI 依赖装配。

**验证：** `uv run pytest tests/test_tui.py -k cli`，期望全部通过。

## T51：更新用户文档

**文件：** `README.md`
**依赖：** T50

**步骤：**
1. 列出六个工具和每轮最多一个工具的限制。
2. 说明工作区相对路径、`.gitignore` 和 UTF-8 边界。
3. 说明命令、写入、修改逐次确认，只有 `y`/`yes` 批准。
4. 明确 shell 命令没有操作系统级沙箱，并保留现有配置与密钥警告。

**验证：** `rg -n "read_file|write_file|edit_file|run_command|glob_files|search_code|sandbox|\.gitignore" README.md`，期望每项都有明确说明。

## T52：执行全量回归与启动检查

**文件：** 本阶段全部创建和修改文件
**依赖：** T1-T51

**步骤：**
1. 运行全量测试与 Python 编译检查。
2. 使用空 HOME 验证模块入口和 console script 返回干净的配置缺失错误。
3. 检查真实 API key、空白错误、文件清单和未修改的示例配置。
4. 按已批准的 `checklist.md` 执行最终验收。

**验证：**

```bash
uv run pytest
uv run python -m compileall mewcode tests
env HOME="$(mktemp -d)" uv run python -m mewcode
env HOME="$(mktemp -d)" uv run mewcode
git diff --check
git status --short
```

期望测试和编译通过；两个启动命令因配置缺失返回 `1` 且没有堆栈；diff 无空白错误；改动范围与文件清单一致。

## 执行顺序

```text
T1 → T2 → T3 ─┬→ T4 ─────────────────────────────┐
              ├→ T5 → T6                        │
              └→ T7 → T8 → T9 → T10             │
                         │                        │
T4 + T6 + T7 → T11 → T12 → T13 → T14             │
                         ├→ T15 → T16             │
                         ├→ T17 → T18 → T19       │
                         │          └→ T20 → T21  │
                         ├→ T22 → T23             │
                         ├→ T24 → T25 → T26       │
                         └→ T27 → T28 → T29 → T30│
T6 + T16 + T21 + T23 + T26 + T30 → T31           │
T4 + T31 → T32 → T33 → T34 → T35 ────────────────┤
T4 + T31 → T36 → T37 → T38 → T39 ────────────────┤
                                                  ▼
                              T40 → T41 → T42 → T43
                                             ├→ T44
                                             ├→ T45
                                             └→ T46
                                      T44-T46 → T47
                                                  ↓
                                      T48 → T49 → T50 → T51 → T52
```

T15-T30 可在各自依赖满足后分支推进；T32-T35 与 T36-T39 可分别实现，但开发过程仍按任务验证证据逐项标记。

## 覆盖检查

| Spec | 对应任务 |
|---|---|
| F1 | T2-T3、T5-T6、T31 |
| F2 | T5-T6、T31-T39 |
| F3 | T7、T15-T16 |
| F4 | T8、T17-T19 |
| F5 | T20-T21 |
| F6 | T27-T30 |
| F7 | T9-T10、T22-T23 |
| F8 | T9-T10、T24-T26 |
| F9 | T7-T10、T15-T30 |
| F10 | T12、T17-T21、T27-T30、T48-T49 |
| F11 | T3、T11-T14、T16、T19、T23、T25、T29-T30 |
| F12 | T14、T16、T23、T26、T30 |
| F13 | T4、T32-T40 |
| F14 | T40-T44 |
| F15 | T45-T47 |
| F16 | T13-T14、T48-T50 |
| N1-N12 | T2-T52 的安全、隔离、测试、兼容、文档和回归步骤 |
