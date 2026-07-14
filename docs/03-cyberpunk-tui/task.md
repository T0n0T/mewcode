# MewCode Cyberpunk TUI Tasks

## 执行规则

- 每个任务是约 2–5 分钟的聚焦工作单元。
- 只在依赖任务验证通过后开始后续任务。
- 每个任务完成后先运行对应验证，再更新任务状态。
- 阶段检查点运行更宽范围测试，避免局部验证掩盖回归。
- 四份里程碑文档全部批准前不得执行这些实现任务。

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `pyproject.toml` | 增加 Textual 运行依赖及 TUI 测试依赖 |
| 修改 | `uv.lock` | 锁定新增依赖 |
| 修改 | `README.md` | 说明全屏模式、纯文本回退和核心按键 |
| 修改 | `mewcode/cli.py` | 检测终端模式并装配对应界面 |
| 修改 | `mewcode/runtime.py` | 输出回合事件并保护中断历史语义 |
| 新建 | `mewcode/turns.py` | 回合阶段、事件、取消控制与中断信号 |
| 修改 | `mewcode/providers/base.py` | Provider 协议接入取消控制 |
| 修改 | `mewcode/providers/openai.py` | OpenAI 活动流关闭与中断转换 |
| 修改 | `mewcode/providers/anthropic.py` | Anthropic 活动流关闭与中断转换 |
| 删除 | `mewcode/tui.py` | 由新的 TUI 深模块替代 |
| 新建 | `mewcode/tui/__init__.py` | TUI 公共入口 |
| 新建 | `mewcode/tui/mode.py` | TTY 检测和终端模式 |
| 新建 | `mewcode/tui/app.py` | Textual 应用、Worker 和状态编排 |
| 新建 | `mewcode/tui/events.py` | 线程间 Textual Message |
| 新建 | `mewcode/tui/interaction.py` | TUI 工具事件桥和确认协调 |
| 新建 | `mewcode/tui/metadata.py` | 会话元数据与 Git 分支探测 |
| 新建 | `mewcode/tui/plain.py` | 非 TTY 应用与纯文本工具交互 |
| 新建 | `mewcode/tui/cyberpunk.tcss` | 主题、布局和响应式规则 |
| 新建 | `mewcode/tui/widgets/__init__.py` | Widget 内部入口 |
| 新建 | `mewcode/tui/widgets/chrome.py` | 顶部栏、欢迎卡和活动提示 |
| 新建 | `mewcode/tui/widgets/conversation.py` | 对话、消息、工具卡和错误卡 |
| 新建 | `mewcode/tui/widgets/composer.py` | 多行输入与提示历史 |
| 新建 | `mewcode/tui/widgets/confirmation.py` | 危险操作确认弹层 |
| 新建 | `tests/test_cli.py` | CLI 模式选择与装配 |
| 新建 | `tests/test_turns.py` | 回合事件及取消竞态 |
| 修改 | `tests/test_runtime.py` | 回合事件、阶段和中断历史 |
| 修改 | `tests/test_providers.py` | 双 Provider 取消与回归 |
| 删除 | `tests/test_tui.py` | 拆分为聚焦测试 |
| 新建 | `tests/test_tui_mode.py` | 终端模式检测 |
| 新建 | `tests/test_tui_plain.py` | 纯文本交互 |
| 新建 | `tests/test_tui_app.py` | Textual 应用端到端行为 |
| 新建 | `tests/test_tui_widgets.py` | Widget、Markdown、滚动和响应式行为 |
| 新建 | `tests/test_tui_interaction.py` | 工具卡、确认和脱敏 |
| 新建 | `tests/test_tui_metadata.py` | 会话元数据降级 |
| 新建 | `tests/snapshots/` | 少量关键终端布局快照 |

## T1：加入 TUI 依赖

**文件：** `pyproject.toml`、`uv.lock`
**依赖：** 无

**步骤：**

1. 使用 `uv` 增加 Textual 运行时依赖。
2. 增加 `pytest-asyncio` 与 `pytest-textual-snapshot` 作为开发依赖。
3. 同步全部依赖组并确认没有新增配置字段。

**验证：**

`uv sync --all-groups && uv run python -c "from importlib.metadata import version; print(version('textual'))"`

## T2：定义回合阶段与事件

**文件：** `mewcode/turns.py`、`tests/test_turns.py`
**依赖：** T1

**步骤：**

1. 定义 `TurnPhase`、`TurnPhaseChanged`、`TurnTextDelta` 和 `TurnCompleted`。
2. 定义 `TurnEvent` 联合类型和 `TurnInterrupted`。
3. 测试事件不可变、阶段值稳定且中断信号不属于用户错误类型。

**验证：**

`uv run pytest tests/test_turns.py -q`

## T3：实现取消状态与幂等操作

**文件：** `mewcode/turns.py`、`tests/test_turns.py`
**依赖：** T2

**步骤：**

1. 使用锁实现 `TurnCancellation.is_cancelled`。
2. 实现可重复调用的 `cancel()`。
3. 实现 `raise_if_cancelled()`。
4. 测试未取消、预先取消和重复取消。

**验证：**

`uv run pytest tests/test_turns.py -q -k cancellation`

## T4：实现活动流关闭绑定

**文件：** `mewcode/turns.py`、`tests/test_turns.py`
**依赖：** T3

**步骤：**

1. 实现 `bind_stream_closer()` 上下文管理器。
2. 保证先取消后绑定会立即关闭。
3. 保证活动绑定期间取消只关闭一次。
4. 保证退出上下文后不会关闭过期流。
5. 使用线程同步原语覆盖绑定与取消竞态。

**验证：**

`uv run pytest tests/test_turns.py -q`

## T5：更新 Provider 协议与测试替身

**文件：** `mewcode/providers/base.py`、`tests/test_providers.py`、`tests/test_runtime.py`、现有假 Provider 所在测试文件
**依赖：** T4

**步骤：**

1. 为 `LLMProvider.stream_response` 增加 `TurnCancellation` 参数。
2. 更新测试中的 Provider 替身和直接调用点。
3. 保持 ProviderEvent、消息结构和序列化类型不变。

**验证：**

`uv run pytest --collect-only -q && uv run python -m compileall mewcode tests`

## T6：为 OpenAI 流接入取消

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T5

**步骤：**

1. 请求前检查取消状态。
2. 进入响应上下文后绑定响应关闭函数。
3. 解析每个 SSE 事件时检查取消状态。
4. 取消导致的关闭转换为 `TurnInterrupted`，不包装为连接错误。
5. 添加预取消、活动关闭和原有错误脱敏回归测试。

**验证：**

`uv run pytest tests/test_providers.py -q -k openai`

## T7：为 Anthropic 流接入取消

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T5

**步骤：**

1. 请求前检查取消状态。
2. 进入响应上下文后绑定响应关闭函数。
3. 解析每个 SSE 事件时检查取消状态。
4. 取消导致的关闭转换为 `TurnInterrupted`。
5. 添加预取消、活动关闭、thinking 保留和错误脱敏回归测试。

**验证：**

`uv run pytest tests/test_providers.py -q -k anthropic`

## T8：让普通运行时回合输出事件

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T6、T7

**步骤：**

1. 为 `stream_turn` 增加取消控制参数。
2. 普通回合开始时输出 `INITIAL_RESPONSE`。
3. 把 Provider 文本片段转换为 `TurnTextDelta`。
4. 成功提交助手历史后输出 `TurnCompleted`。
5. 更新普通回复和多轮历史测试。

**验证：**

`uv run pytest tests/test_runtime.py -q -k "plain or history"`

## T9：为工具回合输出最终阶段

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T8

**步骤：**

1. 保留首个完整助手工具请求的历史提交。
2. 工具反馈加入历史后输出 `FINAL_RESPONSE`。
3. 最终文本继续输出 `TurnTextDelta`，正常结束后输出 `TurnCompleted`。
4. 覆盖单工具、多个工具、无效参数和二次工具请求。

**验证：**

`uv run pytest tests/test_runtime.py -q -k tool`

## T10：保护运行时中断历史

**文件：** `mewcode/runtime.py`、`tests/test_runtime.py`
**依赖：** T9

**步骤：**

1. 在消费 Provider 事件和提交历史前检查取消状态。
2. 覆盖首片段前取消、部分文本后取消和最终回复阶段取消。
3. 断言用户消息保留，未完成助手回复不进入历史。
4. 断言工具已完成时不伪造副作用回滚，且不再请求最终回复。

**验证：**

`uv run pytest tests/test_runtime.py -q -k "cancel or interrupt"`

## T11：运行 Provider 与运行时检查点

**文件：** 本阶段已修改文件
**依赖：** T10

**步骤：**

1. 运行回合、Provider、SSE 和工具执行测试。
2. 修复事件签名变化造成的遗漏调用点。
3. 确认代码可编译且没有循环导入。

**验证：**

`uv run pytest tests/test_turns.py tests/test_runtime.py tests/test_providers.py tests/test_sse.py tests/test_tool_executor.py -q && uv run python -m compileall mewcode tests`

## T12：把行式界面迁移为 TUI 包

**文件：** `mewcode/tui.py`、`mewcode/tui/__init__.py`、`mewcode/tui/plain.py`、`mewcode/tui/widgets/__init__.py`
**依赖：** T11

**步骤：**

1. 创建 `mewcode/tui/` 包和 Widget 子包。
2. 把现有行式应用、工具交互、常量和参数摘要迁入 `plain.py`。
3. 暂时通过包入口导出兼容名称，保证 CLI 可以继续导入。
4. 删除旧 `mewcode/tui.py`。

**验证：**

`uv run python -c "from mewcode.tui import ChatApp, TerminalToolInteraction; print(ChatApp.__name__)"`

## T13：让纯文本应用消费回合事件

**文件：** `mewcode/tui/plain.py`、`tests/test_tui_plain.py`
**依赖：** T12

**步骤：**

1. 将行式应用改名为 `PlainChatApp`。
2. 每轮创建 `TurnCancellation`，并消费 `TurnPhaseChanged`、`TurnTextDelta` 和 `TurnCompleted`。
3. 使用 `›`、`◆` 和线性阶段记录，移除所有 `assistant` 文案。
4. 保留空输入、错误恢复、`exit`、`quit` 和 EOF 行为。
5. 迁移对应旧测试。

**验证：**

`uv run pytest tests/test_tui_plain.py -q`

## T14：实现终端模式检测

**文件：** `mewcode/tui/mode.py`、`mewcode/tui/__init__.py`、`tests/test_tui_mode.py`
**依赖：** T12

**步骤：**

1. 定义 `TerminalMode.FULLSCREEN` 与 `PLAIN`。
2. 仅在实际标准输入输出均为 TTY 时选择全屏。
3. 对注入流、缺失 `isatty`、检测异常及任一非 TTY 情况回退。
4. 添加完整决策表测试。

**验证：**

`uv run pytest tests/test_tui_mode.py -q`

## T15：构建安全会话元数据

**文件：** `mewcode/tui/metadata.py`、`tests/test_tui_metadata.py`
**依赖：** T12

**步骤：**

1. 定义不包含 API key 的 `SessionMetadata`。
2. 使用固定参数、无 shell、短超时的 Git 查询读取分支。
3. 覆盖普通分支、detached HEAD、非仓库、Git 缺失和超时。
4. 确保任何探测失败只返回 `None`。

**验证：**

`uv run pytest tests/test_tui_metadata.py -q`

## T16：定义线程间界面消息

**文件：** `mewcode/tui/events.py`、`tests/test_tui_app.py`
**依赖：** T1、T12

**步骤：**

1. 定义 `ActivityState` 以及阶段、文本、完成、中断和错误 Message。
2. 定义工具开始、工具完成和确认请求 Message。
3. 所有回合消息携带 generation id，工具消息携带 call id。
4. 测试消息只保存不可变展示数据。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k message`

## T17：实现一次性绑定的 TUI Bridge

**文件：** `mewcode/tui/interaction.py`、`tests/test_tui_interaction.py`
**依赖：** T16

**步骤：**

1. 实现未绑定、已绑定和已关闭状态。
2. 只允许 Bridge 成功绑定一个应用目标。
3. 从工作线程通过目标的线程安全入口发送事件。
4. 关闭时拒绝新事件并解析全部未决确认。

**验证：**

`uv run pytest tests/test_tui_interaction.py -q -k bridge`

## T18：实现 TUI 工具状态事件

**文件：** `mewcode/tui/interaction.py`、`tests/test_tui_interaction.py`
**依赖：** T17

**步骤：**

1. 实现 `TuiToolInteraction.tool_started`。
2. 实现 `tool_finished` 和工具额度耗尽事件。
3. 只发送工具名、调用标识、脱敏参数摘要、状态、耗时和安全错误。
4. 断言完整结果与密钥不会进入展示消息。

**验证：**

`uv run pytest tests/test_tui_interaction.py -q -k "tool and not confirmation"`

## T19：实现异步确认协调

**文件：** `mewcode/tui/interaction.py`、`tests/test_tui_interaction.py`
**依赖：** T18

**步骤：**

1. 为每次确认创建 `Future[bool]`。
2. 将脱敏预览发送给主线程并阻塞当前工具工作线程。
3. 覆盖批准、拒绝、弹层关闭、应用退出和回合取消。
4. 保证 Future 只解析一次。

**验证：**

`uv run pytest tests/test_tui_interaction.py -q -k confirmation`

## T20：建立主题与资源加载

**文件：** `mewcode/tui/cyberpunk.tcss`、`mewcode/tui/app.py`、`pyproject.toml`、`tests/test_tui_app.py`
**依赖：** T1、T12

**步骤：**

1. 定义石墨黑、青蓝、洋红、成功、警告、错误和弱化文本色。
2. 定义根布局、顶部栏、对话区、输入区、卡片和弹层基础样式。
3. 增加单色类和 wide、compact、narrow、too-small 状态类。
4. 配置应用 CSS 资源路径。
5. 测试源码环境能够加载样式文件。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k css`

## T21：实现顶部栏与欢迎卡

**文件：** `mewcode/tui/widgets/chrome.py`、`mewcode/tui/widgets/__init__.py`、`tests/test_tui_widgets.py`
**依赖：** T15、T20

**步骤：**

1. 实现 `SessionHeader` 的品牌、模型、工作区、分支和连接状态。
2. 实现紧凑猫咪 `WelcomeCard` 与能力边界文案。
3. 保证两者不接收或保留 API key。
4. 测试完整字段与缺失分支降级。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k "header or welcome"`

## T22：实现活动与新输出提示

**文件：** `mewcode/tui/widgets/chrome.py`、`tests/test_tui_widgets.py`
**依赖：** T16、T21

**步骤：**

1. 实现 `ActivityIndicator` 的状态词、模型或工具名、旋转符号和单调计时。
2. 实现 `NewOutputIndicator` 的未读计数和返回底部事件。
3. 保证 READY 状态停止计时和动画。
4. 测试 UPLINKING、EXECUTING、SYNTHESIZING 与 INTERRUPTED 文案。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k "activity or new_output"`

## T23：实现会话内提示历史

**文件：** `mewcode/tui/widgets/composer.py`、`tests/test_tui_widgets.py`
**依赖：** T20

**步骤：**

1. 实现记录非空提示、游标移动和导航重置。
2. 首次向上时保存当前草稿。
3. 向下回到末尾时恢复草稿。
4. 测试重复文本、边界移动和空历史。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k prompt_history`

## T24：实现多行 PromptComposer

**文件：** `mewcode/tui/widgets/composer.py`、`mewcode/tui/widgets/__init__.py`、`tests/test_tui_widgets.py`
**依赖：** T23

**步骤：**

1. 基于 TextArea 实现一至六行动态高度。
2. 绑定 Enter 提交、Shift+Enter 与 Ctrl+J 换行。
3. 保持多行粘贴为单个草稿。
4. 忙碌时保留编辑能力但抑制提交。
5. 仅在输入为空时把上下键交给提示历史。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k composer`

## T25：实现用户与回复消息视图

**文件：** `mewcode/tui/widgets/conversation.py`、`mewcode/tui/widgets/__init__.py`、`tests/test_tui_widgets.py`
**依赖：** T20

**步骤：**

1. 实现带 `›` 的 `UserMessageView`。
2. 实现带 `◆` 的 `AssistantMessageView` 容器。
3. 增加 ASCII 字形切换入口。
4. 断言任何消息视图都不渲染 `assistant`。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k message_view`

## T26：接入流式 Markdown

**文件：** `mewcode/tui/widgets/conversation.py`、`tests/test_tui_widgets.py`
**依赖：** T25

**步骤：**

1. 为每个回复创建独立 Markdown 流。
2. 实现追加片段、结束流和中断标记。
3. 覆盖分片标题、列表、引用、表格、行内代码与代码围栏。
4. 配置代码、diff 和命令块横向溢出，不强制折行。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k markdown`

## T27：实现智能滚动

**文件：** `mewcode/tui/widgets/conversation.py`、`tests/test_tui_widgets.py`
**依赖：** T22、T26

**步骤：**

1. 实现位于底部时自动跟随。
2. 用户向上滚动后冻结当前位置并累计未读输出。
3. 实现 End 键和 NewOutputIndicator 返回底部。
4. 保证窗口缩放不重置冻结状态。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k scroll`

## T28：实现工具卡与错误卡

**文件：** `mewcode/tui/widgets/conversation.py`、`tests/test_tui_widgets.py`
**依赖：** T18、T20

**步骤：**

1. 实现按 call id 原地更新的 `ToolCard`。
2. 默认折叠参数、错误和截断元数据。
3. 实现不会覆盖既有内容的 `ErrorCard`。
4. 确认两类卡片只渲染脱敏展示数据。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k "tool_card or error_card"`

## T29：实现安全确认弹层

**文件：** `mewcode/tui/widgets/confirmation.py`、`mewcode/tui/widgets/__init__.py`、`tests/test_tui_widgets.py`
**依赖：** T19、T20

**步骤：**

1. 实现命令或 diff 预览区域。
2. 默认聚焦拒绝按钮。
3. Y 或显式批准按钮返回 True；N、Esc 和关闭返回 False。
4. 长预览支持滚动，弹层缩放不丢失决定状态。

**验证：**

`uv run pytest tests/test_tui_widgets.py -q -k confirmation_modal`

## T30：组装全屏应用壳

**文件：** `mewcode/tui/app.py`、`mewcode/tui/__init__.py`、`tests/test_tui_app.py`
**依赖：** T21、T22、T24、T27、T28、T29

**步骤：**

1. 组合 Header、Conversation、Composer、Activity 和弹层入口。
2. 初始显示欢迎卡并把焦点放入 Composer。
3. 建立 `ActivityState` 与唯一活动 generation id。
4. 将 Bridge 一次性绑定到应用。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k "mount or focus or welcome"`

## T31：实现普通 TurnWorker 流程

**文件：** `mewcode/tui/app.py`、`mewcode/tui/events.py`、`tests/test_tui_app.py`
**依赖：** T30、T10

**步骤：**

1. 提交提示时显示用户消息并启动线程 Worker。
2. INITIAL_RESPONSE 映射为 UPLINKING。
3. 首片段将等待位置转换为回复视图。
4. TurnCompleted 结束 Markdown、恢复 READY 和提交能力。
5. 使用假运行时验证完整普通回合。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k normal_turn`

## T32：实现文本批处理与顺序屏障

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T31

**步骤：**

1. 为当前 generation 建立线程安全文本缓冲区。
2. 首片段仅安排一次下一事件循环刷新。
3. 阶段、完成、错误与中断处理前先清空剩余文本。
4. 测试大量单字符片段不丢失、不重复且顺序稳定。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k "batch or rapid_chunks"`

## T33：实现工具回合界面编排

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T28、T29、T32

**步骤：**

1. 工具开始事件创建或更新 EXECUTING 卡片。
2. 确认请求打开弹层并解析 Future。
3. 工具完成事件原地更新状态与耗时。
4. FINAL_RESPONSE 映射为 SYNTHESIZING，并创建独立最终回复。
5. 覆盖无前言、有前言、拒绝、失败和多个工具拒绝路径。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k tool_turn`

## T34：实现界面错误边界

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T32

**步骤：**

1. MewCodeError 映射为带安全消息的 ErrorCard。
2. 意外异常映射为无堆栈的通用错误。
3. 保留错误前已经显示的片段。
4. 错误后恢复 Composer 和 READY 状态。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k error`

## T35：实现中断与迟到事件过滤

**文件：** `mewcode/tui/app.py`、`tests/test_tui_app.py`
**依赖：** T10、T31、T34

**步骤：**

1. Esc 和生成中的 Ctrl+C 取消当前控制器。
2. 立即显示 INTERRUPTED，并保留已有 Markdown。
3. 使当前 generation id 失效并忽略迟到事件。
4. Worker 确认结束后恢复提交，期间允许继续编辑草稿。
5. 覆盖 Provider 等待、部分回复、确认弹层和工具执行中断。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k "interrupt or stale"`

## T36：实现输入历史、草稿与退出状态机

**文件：** `mewcode/tui/app.py`、`mewcode/tui/widgets/composer.py`、`tests/test_tui_app.py`
**依赖：** T24、T35

**步骤：**

1. 成功提交后记录提示历史。
2. 生成期间保留下一条草稿但拒绝 Enter 提交。
3. Ctrl+C 在有内容时清空输入。
4. 空输入第一次 Ctrl+C 显示退出提示，2 秒内再次按下退出。
5. 空输入 Ctrl+D、`exit` 和 `quit` 直接退出。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k "history or draft or exit"`

## T37：实现响应式与能力降级

**文件：** `mewcode/tui/app.py`、`mewcode/tui/plain.py`、`mewcode/tui/cyberpunk.tcss`、`tests/test_tui_app.py`、`tests/test_tui_widgets.py`
**依赖：** T30、T36

**步骤：**

1. Resize 时应用 wide、compact、narrow 或 too-small 类。
2. 低于 48×14 显示尺寸提示且保留草稿。
3. 根据输出编码让全屏和纯文本模式切换 Unicode 与 ASCII 字形。
4. 检测 NO_COLOR 时应用单色类。
5. 覆盖 120×36、80×24、60×18 和 40×10。

**验证：**

`uv run pytest tests/test_tui_app.py tests/test_tui_widgets.py -q -k "responsive or no_color or ascii"`

## T38：加入关键布局快照

**文件：** `tests/test_tui_app.py`、`tests/snapshots/`
**依赖：** T33、T34、T37

**步骤：**

1. 添加宽屏空白会话快照。
2. 添加 80 列流式回复与工具卡快照。
3. 添加窄屏和 NO_COLOR 快照。
4. 避免把计时值、临时路径和随机标识写入快照。

**验证：**

`uv run pytest tests/test_tui_app.py -q -k snapshot`

## T39：接入 CLI 模式装配

**文件：** `mewcode/cli.py`、`mewcode/tui/__init__.py`、`tests/test_cli.py`
**依赖：** T14、T15、T19、T38

**步骤：**

1. 在创建 ToolExecutor 前解析实际输入输出和终端模式。
2. PLAIN 分支装配 PlainToolInteraction、运行时和 PlainChatApp。
3. FULLSCREEN 分支装配 Bridge、TuiToolInteraction、运行时和 CyberpunkChatApp。
4. 保留配置错误、工作区固定和退出码行为。
5. 使用注入流验证 CLI 自动选择纯文本，使用替代应用验证全屏分支。

**验证：**

`uv run pytest tests/test_cli.py -q`

## T40：移除兼容入口并迁移旧测试

**文件：** `mewcode/tui/__init__.py`、`tests/test_tui.py`、`tests/test_tui_plain.py`、`tests/test_cli.py`、其他受影响测试
**依赖：** T39

**步骤：**

1. 删除临时 `ChatApp` 与 `TerminalToolInteraction` 兼容别名。
2. 将旧 TUI 测试全部迁移到新的聚焦测试文件。
3. 删除 `tests/test_tui.py`。
4. 搜索并移除旧类名、旧 `assistant` 文案和旧字符串流假设。

**验证：**

`! rg -n '\b(ChatApp|TerminalToolInteraction)\b|╰─ assistant' mewcode tests && uv run pytest tests/test_tui_*.py tests/test_cli.py -q`

## T41：更新用户文档

**文件：** `README.md`
**依赖：** T40

**步骤：**

1. 说明真实 TTY 自动进入全屏界面。
2. 说明管道、重定向和测试流使用纯文本模式。
3. 记录 Enter、Shift+Enter、Esc、Ctrl+C、Ctrl+D、End、exit 和 quit。
4. 明确本阶段没有斜杠命令、主题配置或持久化历史。

**验证：**

`rg -n "Shift\+Enter|NO_COLOR|plain|Esc|Ctrl\+C" README.md`

## T42：执行完整交付验证

**文件：** 全部改动文件
**依赖：** T41

**步骤：**

1. 运行全部测试和编译检查。
2. 构建 wheel 并确认包含 `cyberpunk.tcss`。
3. 验证 `uv run python -m mewcode` 与 `uv run mewcode` 两个入口。
4. 在伪 TTY 中验证全屏启动，在重定向输出中验证无控制序列。
5. 检查 diff、密钥、占位符和无关改动。

**验证：**

`uv run pytest && uv run python -m compileall mewcode tests && uv build --wheel && unzip -l "$(ls -t dist/*.whl | head -n 1)" | rg "mewcode/tui/cyberpunk.tcss"`

## 执行顺序

```text
T1 → T2 → T3 → T4 → T5
                       ├→ T6 ─┐
                       └→ T7 ─┴→ T8 → T9 → T10 → T11
                                                ↓
T12 → T13
 ├──→ T14
 ├──→ T15
 └──→ T16 → T17 → T18 → T19

T20 → T21 → T22
 ├──→ T23 → T24
 ├──→ T25 → T26 → T27
 ├──→ T28
 └──→ T29

T21 + T22 + T24 + T27 + T28 + T29
                    ↓
                  T30 → T31 → T32
                               ├→ T33 ─┐
                               └→ T34 ─┴→ T35 → T36 → T37 → T38
                                                        ↓
T14 + T15 + T19 + T38 ───────────────────────────────→ T39
                                                             ↓
T40 → T41 → T42
```

## 建议提交点

- **C1（T1–T4）：** TUI 依赖与可取消回合原语。
- **C2（T5–T11）：** Provider 和运行时事件化。
- **C3（T12–T15）：** TUI 深模块、纯文本回退与元数据。
- **C4（T16–T22）：** 线程桥、工具交互和界面框架组件。
- **C5（T23–T29）：** 输入、Markdown、滚动、卡片与弹层。
- **C6（T30–T38）：** 全屏应用状态机、响应式行为和快照。
- **C7（T39–T41）：** CLI 装配、旧接口清理和 README。
- **C8（T42）：** 完整验证；仅在修复验证问题时产生代码提交。

## 自检结果

- plan.md 中的每个模块至少有一个对应任务。
- 每个任务均包含明确文件、依赖、步骤和验证命令。
- T1–T42 存在合法执行顺序，没有循环依赖。
- 类型与接口名称和 plan.md 保持一致。
- 没有把斜杠命令、Agent steering、模型切换、持久化历史或主题配置带入任务范围。
