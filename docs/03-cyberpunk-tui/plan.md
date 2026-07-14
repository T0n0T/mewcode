# MewCode Cyberpunk TUI Plan

## 架构概览

整体采用“终端模式选择 + Textual 展示层 + 后台回合控制 + 现有运行时”的结构：

```text
CLI bootstrap
├── interactive TTY
│   └── CyberpunkChatApp
│       ├── Header / Conversation / Composer / Overlay
│       ├── TurnWorker ──→ ChatRuntime ──→ Provider
│       └── TuiToolInteraction ──→ ToolExecutor
└── non-interactive streams
    └── PlainChatApp ──→ ChatRuntime
```

### 终端模式选择

CLI 完成现有配置、Provider、工具和工作区装配后，检查输入与输出是否均为交互式终端：

- 两者都是 TTY：启动 Textual 全屏应用。
- 任意一端不是 TTY：启动线性纯文本应用。
- 配置加载等启动错误仍通过现有错误流输出，不进入全屏界面。

### Textual 应用壳

`CyberpunkChatApp` 只负责界面状态和用户交互，由以下区域组成：

- `SessionHeader`：品牌、模型、工作区、Git 分支和连接状态。
- `ConversationView`：欢迎卡、用户消息、流式回复、工具卡和错误卡。
- `PromptComposer`：多行编辑、历史导航、草稿和提交控制。
- `ActivityIndicator`：`UPLINKING`、`EXECUTING`、`SYNTHESIZING` 和计时。
- `ConfirmationModal`：危险操作预览与批准/拒绝。
- `NewOutputIndicator`：用户离开底部后的新输出提示。

主题样式集中在 Textual CSS 中，不把颜色、边框和响应式规则散落进业务逻辑。

### 回合工作线程

现有 Provider 和 `ChatRuntime` 保持同步流模型。每个用户回合由单独的 `TurnWorker` 后台线程执行，避免网络等待或工具执行阻塞 Textual 主线程。

工作线程只产生不可变事件；所有组件创建、Markdown 更新、滚动和焦点操作都回到 Textual 主线程完成。

### 运行时展示事件

运行时不依赖 Textual，而是把当前字符串流扩展为界面无关的回合事件：

- 初次请求开始。
- 文本片段到达。
- 进入工具结果回灌后的最终请求。
- 回合正常完成。
- 回合被用户中断。

Textual 和纯文本应用分别解释这些事件。`UPLINKING`、`SYNTHESIZING` 等具体英文文案只存在于展示层。

### 中断控制

每轮创建独立、线程安全的取消控制器：

1. `Esc` 或生成期间的 `Ctrl+C` 立即把界面切换为 `INTERRUPTED`。
2. 控制器通知运行时停止消费事件，并请求关闭当前 Provider 流。
3. 工作线程停止向界面发送后续片段。
4. 运行时在提交历史前再次检查取消状态，确保残缺回复不进入上下文。
5. 用户消息以及中断前已经完整完成的工具调用仍遵循现有历史语义。

用户中断属于正常控制流，不显示为 Provider 错误。

### 工具交互桥

保留现有同步工具执行与确认接口，提供两种实现：

- `TuiToolInteraction`：把开始、完成和额度耗尽转换为界面事件；确认请求交给主线程显示弹层，工作线程等待用户选择。
- `PlainToolInteraction`：在非 TTY 模式下输出脱敏纯文本并读取确认结果。

工具定义、执行额度、安全检查和结果结构不变。

### 纯文本回退

`PlainChatApp` 使用同一运行时事件，但只输出稳定的线性记录：

- 不启用 Textual、颜色、动画或光标控制。
- 使用 `›` 和 `◆` 标记消息。
- 不输出 `assistant`。
- 保留流式文本、工具确认、错误恢复和退出行为。

## 核心数据结构

### 回合阶段与事件

```python
class TurnPhase(Enum):
    INITIAL_RESPONSE = "initial_response"
    FINAL_RESPONSE = "final_response"


@dataclass(frozen=True)
class TurnPhaseChanged:
    phase: TurnPhase


@dataclass(frozen=True)
class TurnTextDelta:
    text: str


@dataclass(frozen=True)
class TurnCompleted:
    pass


TurnEvent = TurnPhaseChanged | TurnTextDelta | TurnCompleted
```

运行时只表达语义阶段：

- `INITIAL_RESPONSE`：首次请求 Provider。
- `FINAL_RESPONSE`：工具反馈已经加入上下文，正在请求最终回复。

展示层分别映射为 `UPLINKING` 和 `SYNTHESIZING`。工具执行状态继续来自工具交互接口，因此运行时不依赖任何界面词汇。

`ChatRuntime` 的入口调整为：

```python
def stream_turn(
    self,
    user_text: str,
    cancellation: TurnCancellation,
) -> Iterator[TurnEvent]:
    ...
```

### 中断控制

```python
class TurnInterrupted(Exception):
    """正常的用户中断信号，不属于可展示错误。"""


class TurnCancellation:
    @property
    def is_cancelled(self) -> bool:
        ...

    def cancel(self) -> None:
        ...

    def raise_if_cancelled(self) -> None:
        ...

    @contextmanager
    def bind_stream_closer(
        self,
        closer: Callable[[], None],
    ) -> Iterator[None]:
        ...
```

`TurnCancellation` 使用锁保护状态，并解决“取消发生在流创建前后”的竞态：

- 已绑定活动流时，`cancel()` 只调用一次关闭函数。
- 流尚未建立时先记录取消；随后绑定的流立即关闭。
- 流退出后解除关闭函数，避免误关下一次请求。
- 运行时在写入每个完整历史消息之前调用 `raise_if_cancelled()`。

Provider 接口增加取消参数，但协议事件保持不变：

```python
def stream_response(
    self,
    history: Sequence[ConversationMessage],
    tools: Sequence[ToolDefinition],
    cancellation: TurnCancellation,
) -> Iterator[ProviderEvent]:
    ...
```

### 展示状态

```python
class ActivityState(Enum):
    READY = "ready"
    UPLINKING = "uplinking"
    STREAMING = "streaming"
    EXECUTING = "executing"
    SYNTHESIZING = "synthesizing"
    INTERRUPTED = "interrupted"
    ERROR = "error"
```

`ActivityState` 只属于展示层。它驱动顶部连接状态、活动指示器、输入提交能力和视觉样式，不进入 Provider 或会话历史。

### 会话元数据

```python
@dataclass(frozen=True)
class SessionMetadata:
    config_name: str
    provider: str
    model: str
    workspace: Path
    git_branch: str | None
```

该结构明确不包含 API key。Git 分支探测失败时使用 `None`，界面隐藏该字段，不影响启动。

### 工具展示事件

```python
@dataclass(frozen=True)
class ToolStartedPresentation:
    call_id: str
    name: str
    argument_summary: str
    started_at: float


@dataclass(frozen=True)
class ToolFinishedPresentation:
    call_id: str
    name: str
    status: ToolStatus
    duration_ms: int
    error_message: str | None
```

事件只携带经过脱敏、适合展示的摘要，不携带完整工具结果。工具卡根据 `call_id` 原地更新，避免开始和结束被渲染成两张无关卡片。

### 确认请求

```python
@dataclass(frozen=True)
class ConfirmationRequest:
    preview: ConfirmationPreview
    decision: Future[bool]
```

后台工作线程提交请求后等待 `decision`。Textual 主线程显示弹层并设置结果；关闭应用、取消回合或关闭弹层时，未完成请求统一解析为 `False`。

### 输入历史

```python
class PromptHistory:
    def record(self, prompt: str) -> None:
        ...

    def previous(self, current_draft: str) -> str:
        ...

    def next(self) -> str:
        ...

    def reset_navigation(self) -> None:
        ...
```

首次向上浏览时暂存当前草稿；向下回到末尾后恢复草稿。历史只存在于当前应用实例中。

### 终端模式

```python
class TerminalMode(Enum):
    FULLSCREEN = "fullscreen"
    PLAIN = "plain"


def detect_terminal_mode(
    input_stream: TextIO,
    output_stream: TextIO,
) -> TerminalMode:
    ...
```

只有输入与输出都明确报告为 TTY 时才返回 `FULLSCREEN`；缺失 `isatty()`、检测异常或任意一端非 TTY 时均安全回退到 `PLAIN`。

## 模块设计

### `turns`：回合事件与中断原语

**职责：**

- 定义 `TurnEvent`、`TurnPhase`、`TurnCancellation` 和 `TurnInterrupted`。
- 提供与 Provider、运行时和界面框架无关的回合控制语义。
- 线程安全地登记并关闭当前活动流。

**依赖：** 仅标准库，不依赖 Textual、Provider 实现或工具模块。

### `runtime`：可观察的回合状态机

**职责：**

- 将现有字符串流改为 `TurnEvent` 流。
- 首次请求前发出 `INITIAL_RESPONSE`。
- 工具结果回灌后发出 `FINAL_RESPONSE`。
- 在接收事件及提交完整历史消息前检查取消状态。
- 用户中断时保留现有用户消息，但不提交未完成的模型回复。
- 保持单工具、单次回灌和工具额度等现有规则不变。

**对外接口：**

```python
ChatRuntime.stream_turn(
    user_text,
    cancellation,
) -> Iterator[TurnEvent]
```

### `providers.base`、`providers.openai`、`providers.anthropic`

**职责：**

- Provider 协议增加 `TurnCancellation` 参数。
- 建立响应流后，将关闭函数绑定到当前取消控制器。
- 每次解析流事件时检查取消状态。
- 用户取消导致的流关闭转换为 `TurnInterrupted`，不包装成网络错误。
- OpenAI、Anthropic 的请求格式、事件转换和历史序列化保持不变。

### `tui` 包外观

原有单文件 TUI 调整为包，并通过包入口只暴露装配所需接口：

```python
detect_terminal_mode(...)
CyberpunkChatApp
PlainChatApp
TuiToolInteraction
PlainToolInteraction
TuiEventBridge
```

内部 Textual 组件、消息类型和 CSS 不成为其他业务模块的依赖。

### `tui.app`：全屏应用与状态编排

**职责：**

- 组合顶部栏、对话区、输入框、活动状态和弹层。
- 接收提交事件，创建本轮取消控制器并启动唯一的后台 `TurnWorker`。
- 将运行时事件映射为 `ActivityState` 和对应组件更新。
- 使用递增的回合标识拒绝处理已取消或过期工作线程发来的事件。
- 生成期间允许编辑草稿，但拒绝提交。
- 实现 `Esc`、`Ctrl+C`、`Ctrl+D` 和双击退出语义。
- 应用退出前取消活动回合，并把所有未决确认解析为拒绝。

只有 Textual 主线程可以创建或修改 Widget。

### `tui.widgets`：可复用界面组件

包含以下组件：

- `SessionHeader`：根据宽度隐藏 Git 分支、工作区等次要字段。
- `ConversationView`：管理消息 Widget、自动跟随状态和未读输出提示。
- `WelcomeCard`：显示紧凑猫咪品牌、模型、工作区和能力边界。
- `UserMessageView`：使用 `›` 渲染用户提示。
- `AssistantMessageView`：使用 `◆` 和流式 Markdown 渲染单次回复。
- `PromptComposer`：封装多行输入、动态高度、粘贴、历史和草稿。
- `ActivityIndicator`：使用单调时钟更新状态、旋转符号和耗时。
- `ToolCard`：通过调用标识原地更新工具状态，细节默认折叠。
- `ErrorCard`：显示安全摘要和默认折叠的技术信息。
- `ConfirmationModal`：默认焦点位于拒绝操作，`Esc` 始终拒绝。
- `NewOutputIndicator`：提示冻结视图下的新内容并提供返回底部操作。

每条回复拥有独立 Markdown 流，新增片段只更新当前回复，不重新渲染完整历史。

### `tui.events`：线程间展示消息

**职责：**

- 定义回合文本、阶段、完成、中断、错误、工具开始、工具完成和确认请求对应的 Textual Message。
- 所有消息携带回合标识；工具消息额外携带调用标识。
- 只传递不可变、已脱敏的展示数据。

### `tui.interaction`：工具交互桥

`TuiEventBridge` 先于应用创建，并在应用装配完成后进行一次性绑定，从而解决“运行时需要工具交互，而工具交互又需要应用”的构造顺序问题。

`TuiToolInteraction` 实现现有工具交互协议：

- 开始和结束事件通过 Bridge 安全发送到 Textual 主线程。
- 确认请求使用 `Future[bool]` 等待弹层结果。
- 关闭弹层、退出应用或取消回合均安全返回拒绝。
- 参数和错误在进入 Bridge 前完成脱敏。

### `tui.plain`：非 TTY 回退

**职责：**

- 以同步方式读取输入并消费同一 `TurnEvent` 流。
- 输出 `›`、`◆` 及必要的线性状态记录。
- 保留工具确认、错误恢复、空输入忽略和现有退出命令。
- 不导入或输出任何动态样式、颜色及光标控制序列。

### `tui.metadata`：只读会话信息

**职责：**

- 从已加载配置和当前工作区构建 `SessionMetadata`。
- 使用固定参数、短超时的只读 Git 查询获取当前分支。
- Git 不存在、当前目录不是仓库、处于 detached HEAD 或查询失败时返回 `None`，不阻止界面启动。

### CLI 装配

CLI 在创建工具执行器前完成终端模式判断：

1. 加载配置、Provider、注册中心和工作区。
2. 根据终端模式创建 TUI 或纯文本工具交互对象。
3. 装配工具执行器与 `ChatRuntime`。
4. 创建对应应用并运行。
5. 全屏模式下，将 `TuiEventBridge` 一次性绑定到应用后再启动事件循环。

配置格式和现有启动错误处理不变。

## 模块交互

### 启动流程

```text
CLI
  → load config / provider / tools / workspace
  → detect terminal mode
  ├─ FULLSCREEN → build bridge → runtime → CyberpunkChatApp → bind bridge → run
  └─ PLAIN      → build PlainToolInteraction → runtime → PlainChatApp → run
```

Git 分支探测与界面元数据构建失败不会影响运行时装配。

### 普通流式回合

```text
PromptComposer
  → submit prompt
  → append UserMessageView
  → start TurnWorker
  → TurnPhaseChanged(INITIAL_RESPONSE)
  → show ◆ UPLINKING <model> · <elapsed>
  → TurnTextDelta
  → transform pending indicator into AssistantMessageView
  → stream Markdown fragments
  → TurnCompleted
  → finalize Markdown and return to READY
```

具体规则：

1. 提交后立即记录会话内输入历史，并在对话区显示用户消息。
2. 活动指示器占据即将生成回复的位置。
3. 首个文本片段到达时，同一位置变为 `◆` 回复，不额外留下状态行。
4. 相邻文本片段按一个渲染帧合并后交给 Markdown 流，避免每个 token 都触发全历史重排。
5. 回合完成后结束当前 Markdown 流，恢复提交能力。
6. 生成期间编辑的下一条草稿保持原样。

### 工具回合

```text
initial provider response
  → optional streamed preamble
  → tool call completed
  → TuiToolInteraction.tool_started
  → ToolCard(EXECUTING)
  → optional ConfirmationModal
  → ToolExecutor
  → ToolCard(success / error / rejected / timeout)
  → TurnPhaseChanged(FINAL_RESPONSE)
  → ◆ SYNTHESIZING · <elapsed>
  → final streamed Markdown response
```

- 初次响应包含正文时，正文、工具卡和最终回复按时间顺序成为三个独立内容块。
- 初次响应没有正文时，不留下空白回复卡。
- 工具卡的展开区域显示脱敏参数摘要、状态、耗时、错误和截断元数据；读取与搜索的完整结果仍只提供给模型，不因界面改造而暴露。
- 多工具拒绝或参数解析失败不会产生虚假的执行卡，但仍进入 `SYNTHESIZING`。
- 确认弹层显示期间，后台工作线程等待 `Future`，Textual 主线程继续响应输入和缩放。
- 弹层 `Esc`、关闭应用或取消回合均解析为拒绝。

### 流式消息合并

后台线程不直接逐 token 更新 Widget：

1. 工作线程把同一回合的连续 `TurnTextDelta` 放入线程安全缓冲区。
2. 第一个未处理片段只安排一次主线程刷新。
3. 主线程取出当前全部片段并写入该回复的 Markdown 流。
4. 刷新期间到达的新片段安排下一帧处理。
5. 阶段变化、工具事件、完成、错误和中断在刷新剩余文本后处理，保证显示顺序稳定。

这样既保持首片段低延迟，也避免快速分片造成事件队列膨胀。

### 中断流程

```text
Esc / Ctrl+C
  → mark current turn INTERRUPTED immediately
  → invalidate current generation id
  → cancel TurnCancellation
  → close active provider stream
  → ignore any stale queued UI event
  → worker acknowledges interruption
  → restore prompt submission
```

- 当前 Markdown 内容保留并追加 `INTERRUPTED` 标记。
- `TurnInterrupted` 不生成错误卡。
- 活动 Provider 流通过已绑定的关闭函数停止。
- 如果已确认的工具正在执行，中断不会宣称撤销已经发生的副作用，也不会强行杀死现有工具；工具按原有语义安全返回后，运行时停止后续 Provider 请求。
- 工作线程完全结束前允许继续编辑草稿，但不启动并发回合。
- 运行时在提交历史前检查取消状态，因此残缺回复不会进入上下文。

### 错误流程

- Provider 在完整响应前失败：保留已经显示的片段但不提交助手历史，并在其后追加错误卡。
- 工具返回结构化失败：更新工具卡，然后按现有规则把失败反馈交给模型生成最终说明。
- 可展示错误只使用经过脱敏的用户安全消息。
- 意外内部异常显示通用错误摘要，不在界面中打印堆栈。
- 错误处理完成后回到 `READY`，用户可继续对话。

### 智能滚动

每次追加内容前记录用户是否位于底部：

- 位于底部：更新后滚动到最新内容。
- 已向上浏览：保持当前偏移并累计未读输出。
- 点击 `NEW OUTPUT ↓` 或按 `End`：回到底部、清零未读并重新启用自动跟随。
- 窗口缩放不会自动重新启用已经冻结的跟随状态。

### 输入与退出

- `Enter` 在空闲状态提交，忙碌状态只保留草稿。
- `Shift+Enter` 始终插入换行。
- 空输入框中的 `↑` / `↓` 交给 `PromptHistory`。
- 生成中 `Ctrl+C` 执行中断。
- 输入框有内容时 `Ctrl+C` 清空。
- 空闲且输入框为空时，第一次 `Ctrl+C` 显示短暂退出提示，限定时间内再次按下才退出。
- 空输入框按 `Ctrl+D` 直接退出。
- 提交文本为 `exit` 或 `quit` 时沿用现有退出行为。

## 文件组织

```text
mewcode/
├── cli.py                         # 修改：终端模式选择与新界面装配
├── runtime.py                     # 修改：输出 TurnEvent 并接入取消检查
├── turns.py                       # 新建：回合事件、阶段和取消控制器
├── providers/
│   ├── base.py                    # 修改：Provider 协议增加取消参数
│   ├── openai.py                  # 修改：绑定并关闭 OpenAI 活动流
│   └── anthropic.py               # 修改：绑定并关闭 Anthropic 活动流
├── tui.py                         # 删除：由 tui/ 深模块替代
└── tui/
    ├── __init__.py                # 公共入口与受控导出
    ├── mode.py                    # TerminalMode 与 TTY 检测
    ├── app.py                     # CyberpunkChatApp、回合 Worker、状态编排
    ├── events.py                  # Textual 线程间 Message
    ├── interaction.py             # TuiEventBridge、TuiToolInteraction、脱敏摘要
    ├── metadata.py                # SessionMetadata 与 Git 分支探测
    ├── plain.py                   # PlainChatApp、PlainToolInteraction
    ├── cyberpunk.tcss             # 色板、布局、断点、动效与 NO_COLOR 样式
    └── widgets/
        ├── __init__.py            # Widget 内部导出
        ├── chrome.py              # Header、Welcome、Activity、NewOutput
        ├── conversation.py        # Conversation、消息、工具卡、错误卡
        ├── composer.py            # PromptComposer 与 PromptHistory
        └── confirmation.py        # ConfirmationModal
```

`tui/__init__.py` 是该深模块的唯一外部入口。CLI 不直接依赖内部 Widget、Textual Message 或 CSS 结构。

### 测试文件

```text
tests/
├── test_cli.py                    # 新建：从旧 TUI 测试迁移 CLI 装配测试
├── test_turns.py                  # 新建：取消竞态、流关闭与幂等性
├── test_runtime.py                # 修改：TurnEvent、阶段和中断历史语义
├── test_providers.py              # 修改：取消绑定及双 Provider 回归
├── test_tui.py                    # 删除：拆分为以下聚焦测试
├── test_tui_mode.py               # 新建：TTY、非 TTY 和检测异常
├── test_tui_plain.py              # 新建：纯文本流、退出、错误、工具确认
├── test_tui_app.py                # 新建：Textual Pilot 端到端交互
├── test_tui_widgets.py            # 新建：输入、滚动、Markdown、响应式布局
├── test_tui_interaction.py        # 新建：工具卡、确认 Future、脱敏
├── test_tui_metadata.py           # 新建：分支探测及失败降级
└── snapshots/                     # 新建：少量稳定的关键布局快照
```

测试共享的假 Provider、延迟流和应用构造器保留在对应测试模块或 pytest fixture 中，不进入生产包。

### 项目与用户文档

```text
pyproject.toml                     # 修改：增加 Textual 运行依赖及异步/快照测试依赖
uv.lock                            # 修改：锁定 Textual 及传递依赖
README.md                          # 修改：说明全屏模式、纯文本回退和核心按键
docs/03-cyberpunk-tui/
├── spec.md                        # 已批准
├── plan.md                        # 本阶段
├── task.md                        # 后续阶段
└── checklist.md                   # 后续阶段
```

构建验证必须确认 `cyberpunk.tcss` 被包含在安装后的 wheel 中，避免源码运行正常但安装版缺少主题。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 全屏框架 | Textual | 原生提供异步事件循环、TextArea、Markdown、滚动容器、ModalScreen、响应式样式和 Pilot 测试，覆盖规格所需能力。 |
| 运行时并发模型 | 保留同步 Provider，在单独线程运行每个回合 | 避免重写双 Provider 和工具执行协议，同时确保界面主线程不被网络或工具阻塞。 |
| 活动回合数量 | 同一时间最多一个 TurnWorker | 维持现有串行会话历史，避免借 UI 改造引入消息队列或并发 Agent 行为。 |
| 运行时到界面的边界 | 使用界面无关的 `TurnEvent` | 运行时不依赖 Textual；全屏和纯文本模式可共享相同状态机。 |
| 文本刷新 | 相邻片段在下一个事件循环刷新点合并 | 不增加固定等待时间，同时避免逐 token 创建 Widget 更新任务。 |
| Markdown | 每个回复独立使用一个流式 Markdown 实例 | 新片段只影响当前回复，历史内容不反复解析；工具前言与最终回答可保持独立。 |
| 中断 | 线程安全取消控制器 + 活动流关闭函数 + 回合标识失效 | 同时覆盖网络流关闭、历史提交保护和迟到界面事件过滤。 |
| 工具取消边界 | 不强杀已经开始的工具，不宣称回滚副作用 | 保持现有工具安全语义；中断后等待工具安全返回并阻止后续模型请求。 |
| 工具确认 | 主线程 ModalScreen + 后台 `Future[bool]` | 弹层保持响应，现有同步工具接口无需变为异步；任何异常关闭都安全拒绝。 |
| 工具结果可见性 | 卡片只显示脱敏摘要、状态、耗时、错误和截断元数据 | 延续现有“完整读取与搜索结果只交给模型”的隐私和可读性边界。 |
| 终端模式检测 | 实际标准输入、输出均为 TTY 才启动全屏；注入流、异常或重定向均回退纯文本 | 避免测试流和日志混入控制序列；全屏应用使用 Textual 自己的终端驱动。 |
| 响应式断点 | `wide ≥100`、`compact 72–99`、`narrow <72`；低于 `48×14` 显示尺寸提示 | 提供确定、可测试的降级规则，同时覆盖常见 80 列终端和分屏。 |
| 色彩降级 | Textual/Rich 终端色彩探测 + `NO_COLOR` 单色样式 | 复用成熟能力，并保证颜色不是唯一的信息载体。 |
| Unicode 降级 | 根据输出编码选择 Unicode 或 ASCII 字形集 | 不支持 `›`、`◆` 和线框字符时改用 `>`、`*` 与 ASCII 边框，避免乱码。 |
| 多行提交 | `Enter` 提交、`Shift+Enter` 换行，并提供 `Ctrl+J` 兼容换行 | 部分终端无法区分 `Shift+Enter`；兼容键不改变主要界面提示和行为。 |
| 双击退出 | 空闲空输入下第一次 `Ctrl+C` 提示，2 秒内再次按下退出 | 降低误退出风险，同时保持终端操作可发现。 |
| Git 分支 | 固定参数、无 shell、短超时的只读 Git 查询 | 正确处理 worktree 等情况；失败只隐藏字段，不影响启动。 |
| CSS 资源 | 独立 `cyberpunk.tcss`，构建测试检查 wheel 内容 | 保持视觉规则集中，并防止安装包遗漏非 Python 资源。 |
| 测试策略 | 业务事件单测 + Textual Pilot 行为测试 + 少量稳定屏幕快照 | 行为断言覆盖交互语义；快照只覆盖关键布局，避免所有颜色或字符变化都造成脆弱测试。 |
| 依赖锁定 | 通过 `uv` 增加 Textual，并加入 `pytest-asyncio` 与 `pytest-textual-snapshot` 开发依赖 | 保持现有依赖管理方式、Pilot 测试能力和可复现安装。 |

## 规格覆盖

| 需求 | 设计归属 |
|---|---|
| F1 全屏单列布局 | `tui.app`、`tui.widgets`、`cyberpunk.tcss` |
| F2 启动与会话信息 | `tui.metadata`、`SessionHeader`、`WelcomeCard` |
| F3 固定视觉主题 | `cyberpunk.tcss`、`ActivityIndicator`、终端能力降级 |
| F4 消息身份 | `UserMessageView`、`AssistantMessageView`、`PlainChatApp` |
| F5 生成阶段 | `TurnPhaseChanged`、`ActivityState`、工具交互事件 |
| F6 流式富文本 | `TurnTextDelta` 缓冲、每回复独立 Markdown 流 |
| F7 代码与宽内容 | `AssistantMessageView`、工具卡及 CSS 横向溢出规则 |
| F8 智能滚动 | `ConversationView`、`NewOutputIndicator` |
| F9 多行输入 | `PromptComposer` |
| F10 草稿与输入历史 | `PromptComposer`、`PromptHistory`、单活动回合约束 |
| F11 中断与退出 | `TurnCancellation`、Provider 流关闭、应用按键状态机 |
| F12 工具事件 | `TuiToolInteraction`、`ToolCard`、`ConfirmationModal` |
| F13 错误反馈 | TurnWorker 错误边界、`ErrorCard`、纯文本错误输出 |
| F14 响应式布局 | Resize 处理、明确断点、CSS 状态类 |
| F15 终端能力适配 | Textual 色彩探测、`NO_COLOR` 样式、ASCII 字形集 |
| F16 非交互输出 | `detect_terminal_mode`、`PlainChatApp`、CLI 装配 |
| F17 界面语言 | TUI 与纯文本展示层的固定英文文案 |

### 非功能需求落实

- **N1、N11：** 运行时只增加展示事件和取消检查；工具、Provider 请求语义及配置格式保持不变。
- **N2、N3、N4：** 后台线程、下一帧片段合并、单回复 Markdown 流和局部 Widget 更新共同保证低延迟与稳定性。
- **N5、N9：** 状态文字、符号、布局、颜色与 ASCII 回退共同表达信息。
- **N6：** 工具数据进入展示事件前统一脱敏，界面元数据不持有 API key。
- **N7：** 流关闭、取消检查和过期回合事件过滤共同保护中断一致性。
- **N8：** Composer 独立保存草稿，提交与编辑状态分离。
- **N10：** 取消控制器、运行时事件、纯文本渲染与 Textual Pilot 分层测试。

### 依赖方向

```text
turns ← providers
turns ← runtime → providers + tools
tui → runtime + turns + config + tools
cli → providers + tools + runtime + tui
```

`runtime`、Provider 和工具层均不反向依赖 `tui`，不存在界面框架向业务层渗透或循环依赖。

规格中的 F1–F17 和 N1–N11 均已有明确设计归属，没有发现未覆盖项。
