# MewCode Tool System Plan

## 架构概览

工具系统采用“统一工具层 + Provider 适配层 + 单轮运行时状态机”的结构。

### 工具层

新增独立工具包，包含：

- 统一工具接口：定义名称、描述、JSON 参数 Schema、无副作用准备阶段和执行阶段。
- 工具注册中心：登记六个核心工具、检查重名、按名称查找，并向 Provider 提供统一元信息。
- 工作区边界组件：集中处理路径规范化、UTF-8 校验、符号链接检查和 `.gitignore` 规则。
- 工具执行器：统一完成参数校验、确认、超时控制、异常转换、结果截断和密钥脱敏。
- 六个工具实现：文件读写修改、shell 命令、文件查找和内容搜索。

写文件、改文件和命令先生成不可产生副作用的执行计划与预览，再交给终端确认；确认通过后才执行。写入类计划会记录原文件状态，落盘前再次检查，避免用户确认后文件已变化却仍按旧预览覆盖。

### Provider 适配层

Provider 不再只返回字符串，而是返回统一流式事件：

```text
文本增量
工具调用开始
工具参数增量
响应完成
```

OpenAI 与 Anthropic 各自负责：

- 把注册中心元信息转换为本协议的工具定义。
- 把原生流式事件转换为统一事件。
- 保留完成工具回灌所需的协议内部响应状态。
- 把统一工具结果转换为本协议要求的后续输入。

协议内部状态对运行时保持不透明。这样可保留 OpenAI 的响应条目以及 Anthropic 的内容块、thinking/signature 等必要信息，而不会把协议细节泄漏到工具层和运行时。

### 运行时层

`ChatRuntime` 从当前的单次文本流扩展为一个固定两阶段状态机，而不是通用循环：

```text
第一次模型响应
├── 只有文本：完成本轮
├── 一个工具调用：执行一次工具 → 回灌结果 → 请求最终回答
├── 多个工具调用：全部拒绝 → 回灌限制错误 → 请求最终回答
└── 参数无法解析：不执行 → 回灌解析错误 → 请求最终回答

第二次模型响应
├── 只有文本：完成本轮
└── 再次调用工具：拒绝并结束，不发起第三次请求
```

运行时负责拼接同一调用标识下的 JSON 参数片段、限制工具数量、调用注册中心与执行器，并且只把协议完整的消息提交到长期会话历史。

### 终端交互层

TUI 继续负责用户输入和文本流显示，并新增一个可注入的工具交互端口，用于：

- 显示工具名称、关键参数和状态。
- 展示命令原文或文件差异预览。
- 收集逐次确认结果。
- 隐藏读取与搜索的完整返回内容。

CLI 启动时以当前启动目录创建工作区对象，装配六个工具、注册中心、执行器、终端交互端口、Provider 和运行时。配置文件格式与查找顺序不变。

## 核心数据结构

### JSONValue 与 ToolDefinition

```python
JSONValue = (
    None
    | bool
    | int
    | float
    | str
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, JSONValue]
```

`input_schema` 使用 JSON Schema。注册时校验名称非空、Schema 合法；调用时统一验证模型参数，不由各工具重复处理基础类型错误。

### ToolResult

```python
ToolStatus = Literal["success", "error", "rejected", "timeout"]


@dataclass(frozen=True)
class ToolErrorInfo:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class TruncationInfo:
    unit: Literal["characters", "bytes", "paths", "matches"]
    original: int
    returned: int
    hint: str


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, JSONValue]
    error: ToolErrorInfo | None = None
    truncation: TruncationInfo | None = None
    duration_ms: int = 0

    def to_model_payload(self) -> dict[str, JSONValue]:
        ...
```

所有执行结果都使用这一结构。命令以非零状态退出时记为 `error`，但 `data` 仍保留退出码、标准输出和标准错误。

### 工具准备与执行

```python
@dataclass(frozen=True)
class ConfirmationPreview:
    kind: Literal["command", "write", "edit"]
    title: str
    details: str


@dataclass(frozen=True)
class PreparedToolAction:
    arguments: dict[str, JSONValue]
    preview: ConfirmationPreview | None
    state: object = field(repr=False)


@dataclass(frozen=True)
class ToolContext:
    workspace: Workspace
    deadline: Deadline
    limits: ToolOutputLimits


class Tool(Protocol):
    definition: ToolDefinition
    requires_confirmation: bool

    def prepare(
        self,
        arguments: Mapping[str, JSONValue],
        context: ToolContext,
    ) -> PreparedToolAction:
        ...

    def execute(
        self,
        action: PreparedToolAction,
        context: ToolContext,
    ) -> ToolResult:
        ...
```

`prepare()` 只验证和生成预览，不得产生目标副作用。写入和修改工具会在 `state` 中保存原文件指纹；确认后执行前重新检查路径边界和文件指纹，状态变化时返回冲突错误。

### 注册与执行

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None:
        ...

    def get(self, name: str) -> Tool | None:
        ...

    def definitions(self) -> tuple[ToolDefinition, ...]:
        ...


class ToolInteraction(Protocol):
    def tool_started(self, call: ToolCall) -> None:
        ...

    def confirm(self, preview: ConfirmationPreview) -> bool:
        ...

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        ...


class ToolExecutor:
    def execute(self, call: ToolCall) -> ToolResult:
        ...
```

执行器负责 Schema 校验、工具查找、准备、确认、超时、异常转换、截断、脱敏和终端状态通知。工具实现只处理自身业务。

### 工具调用与流式片段

```python
@dataclass(frozen=True)
class ToolCallDelta:
    slot: int
    call_id_delta: str = ""
    name_delta: str = ""
    arguments_delta: str = ""


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, JSONValue]


@dataclass(frozen=True)
class ToolFeedback:
    call_id: str
    name: str
    result: ToolResult
```

`slot` 是单次响应内稳定的调用位置，用于在调用 ID、名称或参数尚未完整时归并片段。流结束后才解析 JSON，并要求顶层值为对象。

### 统一 Provider 事件

```python
@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ResponseCompleted:
    provider_state: object = field(repr=False)


ProviderEvent = TextDelta | ToolCallDelta | ResponseCompleted
```

每次成功的 Provider 流必须以一个 `ResponseCompleted` 结束。`provider_state` 保存协议完整响应，运行时只存储和回传，不检查其内部结构。

### 会话历史

```python
@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str
    provider_state: object = field(repr=False)


@dataclass(frozen=True)
class ToolResultsMessage:
    results: tuple[ToolFeedback, ...]


ConversationMessage = UserMessage | AssistantMessage | ToolResultsMessage
```

历史按真实顺序保存用户消息、协议完整的助手响应和工具结果。Provider 各自负责序列化：

```text
OpenAI:
AssistantMessage.provider_state → Responses output items
ToolResultsMessage              → function_call_output items

Anthropic:
AssistantMessage.provider_state → assistant content blocks
ToolResultsMessage              → user tool_result blocks
```

这使 thinking、signature、工具调用 ID 等协议必要信息能够完整重放，同时不进入运行时业务逻辑。

## 核心接口

### Provider 接口

```python
class LLMProvider(Protocol):
    def stream_response(
        self,
        history: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> Iterator[ProviderEvent]:
        ...
```

Provider 每次接收完整历史和工具定义。第一次响应与工具结果回灌后的第二次响应调用同一接口，运行时负责限制调用次数。

### 运行时接口

```python
class ChatRuntime:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
    ):
        ...

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        ...

    def stream_turn(self, user_text: str) -> Iterator[str]:
        ...
```

`stream_turn()` 仍只向 TUI 产出可显示文本，因此现有流式渲染方式保持不变。工具状态和确认通过 `ToolInteraction` 同步完成，不引入双向生成器协议。

## 模块设计

### Provider 基础模块

**职责：** 定义统一会话消息、工具定义、流式事件和 Provider 接口。

现有 `ChatMessage` 将替换为 `UserMessage`、`AssistantMessage` 和 `ToolResultsMessage`。为兼容现有 TUI，运行时仍只向外产出文本字符串。

**依赖：** 不依赖具体 Provider 或工具实现。
**覆盖：** F1、F13、F14、N3、N6。

### OpenAI Provider

**职责：**

- 将统一工具定义转换为 Responses API 工具格式。
- 将会话历史转换为文本输入、函数调用和函数结果输入。
- 解析文本增量、函数调用条目及 JSON 参数增量。
- 保存完整响应条目作为不透明 `provider_state`。
- 将工具结果序列化为稳定 JSON 后回灌。

第一次请求携带全部工具；第二次请求传入空工具列表。运行时仍会拒绝 Provider 意外产生的第二次工具调用。

**覆盖：** F2、F13-F15、N3、N5、N6、N9。

### Anthropic Provider

**职责：**

- 将统一工具定义转换为 Messages API 的 `tools` 格式。
- 将历史转换为 assistant 内容块和 user `tool_result` 内容块。
- 从 `tool_use` 开始事件取得调用 ID 与名称。
- 拼接 `input_json_delta` 参数片段。
- 保存文本、工具调用及协议要求的其他内容块作为 `provider_state`。
- 保持现有 extended thinking 只请求、不显示的行为。

相邻的用户内容与工具结果在序列化时按 Anthropic 所需结构合并，保证第二次工具请求被拒绝后，下一轮历史仍可重放。

**覆盖：** F2、F13-F15、N3、N5、N6、N9。

### 工作区模块

**职责：**

- 启动时固定并解析工作区根目录。
- 拒绝绝对路径和包含 `..` 的工具路径。
- 解析路径及已有父目录中的符号链接，确认最终位置仍在根目录内。
- 区分“读取现有路径”和“创建新路径”的校验方式。
- 加载 `.gitignore` 规则，并始终排除 `.git`。
- 为查找与搜索提供可中断的文件遍历。

显式读取文件不应用忽略规则；只有找文件和搜内容使用忽略规则。

**依赖：** `pathlib`、`pathspec`。
**覆盖：** F3-F9、N1、N8。

### 工具基础与注册中心

**职责：**

- 定义工具、执行计划、确认预览和结构化结果。
- 使用标准 JSON Schema 校验注册信息和调用参数。
- 拒绝空名称、无效 Schema 和重复名称。
- 提供稳定注册顺序，确保测试及 Provider 请求可预测。

参数校验采用 `jsonschema`，并统一禁止 Schema 未声明的参数。

**覆盖：** F1、F2、F11、N4、N10。

### 六个核心工具

| 工具名 | 参数 | 行为 |
|---|---|---|
| `read_file` | `path`、可选 `start_line`、`line_count` | 按行读取 UTF-8 文本 |
| `write_file` | `path`、`content` | 新建或完整覆盖，自动创建父目录 |
| `edit_file` | `path`、`old_text`、`new_text` | 原文唯一匹配替换 |
| `run_command` | `command`、可选 `timeout_seconds` | 使用当前 shell 执行完整命令 |
| `glob_files` | `pattern` | 使用工作区相对 glob 匹配路径 |
| `search_code` | `query`、可选 `path_pattern`、`regex` | 默认字面搜索，可选择正则搜索 |

`write_file` 和 `edit_file` 使用统一 diff 预览及原文件指纹检查，并通过临时文件加原子替换落盘。`search_code` 遇到二进制或无效 UTF-8 文件时跳过并记录跳过数量。

**覆盖：** F3-F8、F10-F12。

### 工具执行器

**职责：**

1. 按名称查找工具。
2. 校验 JSON 参数。
3. 建立 30 秒截止时间。
4. 调用无副作用的 `prepare()`。
5. 展示状态及确认预览。
6. 用户确认后执行。
7. 捕获拒绝、超时、冲突和异常。
8. 截断结果并脱敏。
9. 通知终端最终状态。

文件遍历通过截止时间进行协作式中止；命令使用子进程超时，超时后终止整个进程组。命令输出按 UTF-8 严格解码，非法编码返回结构化错误。

默认上限：

- 文本结果：50,000 字符。
- 文件路径：1,000 条。
- 搜索匹配：500 条。
- 命令的标准输出与标准错误：各 50,000 字符。

**覆盖：** F9-F12、F16、N1、N2、N4、N7、N11。

### 运行时模块

**职责：**

- 维护完整会话历史。
- 拼接同一 `slot` 的工具调用参数。
- 首次响应执行零个或一个工具。
- 多工具时为每个调用生成关联调用 ID 的限制错误，全部不执行。
- 回灌结果后发起且仅发起一次最终响应。
- 第二次再次调用工具时生成拒绝结果、通知终端并结束。
- 只提交完整、可重放的 Provider 状态到历史。

第二次响应会传入空工具列表，但仍保留防御性检查。

**覆盖：** F13-F15、N5、N6、N9、N10。

### TUI 与 CLI 装配

TUI 新增终端工具交互实现，确认提示默认拒绝，只有输入 `y` 或 `yes` 才批准。文件预览使用统一 diff；所有显示内容先做密钥脱敏。

CLI 以调用 `main()` 时的当前目录作为工作区根目录，创建六个工具、注册中心、执行器和运行时。现有配置路径、启动错误和退出行为保持不变。

**覆盖：** F10、F16、N2、N7、N9、N11、N12。

## 模块交互

### 启动装配

```text
CLI main()
  ├── 固定 workspace_root = 当前启动目录
  ├── 加载 LLM 配置
  ├── 创建 Workspace
  ├── 创建并注册六个 Tool
  ├── 创建 TerminalToolInteraction
  ├── 创建 ToolExecutor
  ├── 创建对应 Provider
  ├── 创建 ChatRuntime
  └── 启动 ChatApp
```

`Workspace` 在启动后不可更换。所有工具共享同一个工作区对象、输出限制和安全规则。

### 普通文本响应

```text
用户输入
  → 历史追加 UserMessage
  → Provider.stream_response(history, tools)
  → TextDelta 立即显示
  → ResponseCompleted
  → 历史追加 AssistantMessage
  → 本轮结束
```

Provider 流未正常完成时，不保存残缺助手消息；已经追加的用户消息继续保留，与现有失败行为一致。

### 单工具调用

```text
第一次模型响应
  → 文本增量立即显示
  → 收集 ToolCallDelta
  → ResponseCompleted
  → 按 slot 拼接调用 ID、名称和参数
  → 解析 JSON 参数
  → 历史追加完整 AssistantMessage
  → ToolExecutor.execute()
      ├── 查找工具与校验参数
      ├── prepare()
      ├── 展示工具状态
      ├── 必要时请求确认
      ├── execute()
      └── 返回 ToolResult
  → 历史追加 ToolResultsMessage
  → Provider.stream_response(history, tools=())
  → 流式显示最终文本
  → 历史追加最终 AssistantMessage
  → 本轮结束
```

用户拒绝、工具超时或工具执行失败都属于正常的 `ToolResult`，因此仍会进入第二次模型请求，让模型解释失败并给出最终回答。

### 参数解析失败

工具参数只在第一次响应完整结束后解析。若参数 JSON 不完整、无效或顶层不是对象：

1. 不查找或执行工具。
2. 保存协议完整的助手响应。
3. 创建与调用 ID 关联的结构化参数错误。
4. 将错误作为工具结果回灌。
5. 请求模型生成最终文本。

### 多工具调用

```text
第一次响应包含两个或更多 slot
  → 保存完整 AssistantMessage
  → 不执行任何工具
  → 为每个调用生成 multiple_tool_calls 错误结果
  → 一次性回灌所有错误结果
  → 请求最终文本，tools=()
```

即使其中某个调用本身合法，也不会执行，防止“只执行第一个”造成模型和实际状态不一致。

### 第二次再次调用工具

第二次请求虽然不提供工具定义，运行时仍防御性检查事件：

```text
第二次响应出现 ToolCallDelta
  → 不执行工具
  → 通知终端“本轮工具额度已用完”
  → 丢弃该次响应的协议状态
  → 不写入长期历史
  → 不发起第三次请求
  → 本轮结束
```

第二次响应中的文本增量仍会即时显示；但只要同时出现工具调用，整条响应就不进入历史，避免留下没有对应工具结果的悬空调用。

### 历史提交规则

| 事件 | 写入历史 |
|---|---|
| 用户开始一轮输入 | 写入用户消息 |
| Provider 流中途失败 | 不写入助手消息 |
| 完整普通响应 | 写入助手消息 |
| 完整工具调用响应 | 写入助手消息 |
| 工具成功、失败、拒绝或超时 | 写入工具结果消息 |
| 第二次合法最终回答 | 写入助手消息 |
| 第二次违规工具调用 | 不写入该响应 |

### TUI 交互

`ChatApp` 和 `TerminalToolInteraction` 共享同一组输入输出流：

- `ChatApp` 负责用户问题和助手文本。
- `TerminalToolInteraction` 负责工具状态、预览和确认输入。
- 确认期间暂停模型响应处理，收到 `y` 或 `yes` 后继续。
- 其他输入均视为拒绝。
- 读取与搜索结果只回灌模型，终端只显示摘要及状态。

## 文件组织

```text
mewcode/
├── cli.py
├── runtime.py
├── tui.py
├── errors.py
│
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── openai.py
│   ├── anthropic.py
│   └── sse.py
│
└── tools/
    ├── __init__.py
    ├── base.py
    ├── registry.py
    ├── workspace.py
    ├── executor.py
    ├── file_tools.py
    ├── search_tools.py
    ├── command.py
    └── defaults.py

tests/
├── test_config.py
├── test_sse.py
├── test_runtime.py
├── test_providers.py
├── test_tui.py
├── test_tool_registry.py
├── test_workspace.py
├── test_file_tools.py
├── test_search_tools.py
├── test_command_tool.py
└── test_tool_executor.py

docs/
├── 01-basic-chat/
│   └── ...
└── 02-tool-system/
    ├── spec.md
    ├── plan.md
    ├── task.md
    └── checklist.md

pyproject.toml
README.md
config.yaml.example
```

### 新建文件

| 文件 | 职责 |
|---|---|
| `mewcode/tools/__init__.py` | 导出公开工具类型及默认注册中心构造入口 |
| `mewcode/tools/base.py` | JSON 类型、工具定义、结果、截断信息、执行计划、上下文和工具协议 |
| `mewcode/tools/registry.py` | 工具注册、重名检查、Schema 检查、按名称查找 |
| `mewcode/tools/workspace.py` | 工作区路径边界、符号链接防逃逸、忽略规则和安全遍历 |
| `mewcode/tools/executor.py` | 参数校验、截止时间、确认、执行、异常转换、截断和脱敏 |
| `mewcode/tools/file_tools.py` | `read_file`、`write_file`、`edit_file` |
| `mewcode/tools/search_tools.py` | `glob_files`、`search_code` |
| `mewcode/tools/command.py` | `run_command`、子进程组管理和超时终止 |
| `mewcode/tools/defaults.py` | 创建并注册六个内置工具，集中设置默认输出限制 |
| `tests/test_tool_registry.py` | 注册、重名、Schema 和稳定顺序测试 |
| `tests/test_workspace.py` | 路径逃逸、符号链接、忽略规则和遍历测试 |
| `tests/test_file_tools.py` | UTF-8 读取、新建、覆盖、预览、唯一替换和冲突测试 |
| `tests/test_search_tools.py` | glob、字面搜索、正则搜索、忽略文件、编码跳过和截断测试 |
| `tests/test_command_tool.py` | shell 语义、工作目录、输出、退出码、编码、超时和进程组终止测试 |
| `tests/test_tool_executor.py` | 参数错误、确认、拒绝、超时、异常、脱敏和交互通知测试 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `mewcode/providers/base.py` | 用统一会话消息及 Provider 事件替换纯文本 `ChatMessage` 接口 |
| `mewcode/providers/openai.py` | 工具定义转换、流式调用拼接、Provider 状态保存和结果回灌 |
| `mewcode/providers/anthropic.py` | `tool_use`/参数增量解析、内容块保存和 `tool_result` 回灌 |
| `mewcode/providers/__init__.py` | 保持 Provider 工厂，并导出新的统一类型 |
| `mewcode/runtime.py` | 实现固定两阶段单工具状态机和历史提交规则 |
| `mewcode/tui.py` | 实现工具状态、diff/命令预览及默认拒绝的确认交互 |
| `mewcode/cli.py` | 创建工作区、默认工具、执行器并完成依赖装配 |
| `mewcode/errors.py` | 增加工具系统内部错误类型，公开失败仍转换为 `ToolResult` |
| `tests/test_providers.py` | 增加两个 Provider 的工具定义、流式参数和结果回灌测试 |
| `tests/test_runtime.py` | 增加普通响应、单工具、多工具、解析失败和二次调用限制测试 |
| `tests/test_tui.py` | 增加工具状态、确认、预览和结果隐藏测试 |
| `pyproject.toml` | 增加 `jsonschema` 与 `pathspec` 依赖 |
| `README.md` | 更新工具能力、工作区边界、确认规则及非沙箱警告 |

`config.yaml.example` 不需要修改，因为本阶段不新增配置字段。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 总体编排 | Provider 统一事件 + 运行时固定两阶段状态机 | 两种协议共享单工具限制，且不提前实现 Agent Loop |
| Provider 历史 | 保存不透明的协议完整响应状态 | 工具调用、thinking/signature 等内容可被准确回灌，运行时不依赖协议细节 |
| 工具接口 | `prepare()` 与 `execute()` 分离 | 确认前可生成真实预览，同时保证不提前产生目标副作用 |
| 参数格式 | JSON Schema + `jsonschema` 校验 | 注册元信息与运行时参数共用标准格式，错误位置清楚 |
| 未声明参数 | 所有内置工具 Schema 使用 `additionalProperties: false` | 及时发现模型参数拼写错误，避免工具静默忽略 |
| 忽略规则 | 使用 `pathspec` 解释 `.gitignore` | 避免自行实现复杂 Git ignore 语义 |
| 路径安全 | 仅接受相对路径，解析现有路径和父目录后检查是否仍位于根目录 | 同时防止绝对路径、`..` 和符号链接逃逸 |
| 文件编码 | UTF-8 严格解码与编码 | 非文本或无效编码明确失败，不进行隐式替换 |
| 写入方式 | 同目录临时文件、flush 后原子替换 | 避免写入中断留下半文件，并保持跨文件系统边界可控 |
| 并发变化 | 预览时记录文件指纹，执行前重新校验 | 防止确认内容和实际写入对象不一致 |
| 修改语义 | `old_text` 必须恰好出现一次 | 结果确定，零匹配和多匹配都让模型根据错误重试 |
| shell 执行 | 当前平台默认 shell，工作目录固定为工作区根 | 满足完整命令、管道和重定向需求，不承诺跨平台一致 |
| 命令终止 | 独立进程组，超时终止整个进程组 | 防止 shell 子进程在父进程超时后继续运行 |
| 普通工具超时 | 统一单调时钟截止时间，遍历和读写分块检查 | Python 线程无法可靠强制停止；协作式截止可避免后台操作在返回后继续改文件 |
| 输出限制 | 文本 50,000 字符、路径 1,000 条、匹配 500 条 | 控制模型上下文体积，同时保留足够诊断信息 |
| 截断位置 | 工具产生结构化数据后，由执行器统一限制 | 所有工具获得一致的 `truncation` 语义 |
| 多工具请求 | 全部不执行，为每个调用返回限制错误 | 模型历史与真实副作用保持一致 |
| 第二次请求 | 不提供工具定义，并保留运行时防御性拒绝 | 从请求端减少再次调用概率，同时保证异常 Provider 行为不会越过额度 |
| 第二次违规响应 | 显示已产生文本，但不保存整条响应 | 避免历史中留下没有对应结果的工具调用 |
| 确认输入 | 仅 `y`/`yes` 批准，其余一律拒绝 | 默认安全，非交互输入结束也不会误批准 |
| 工具结果传输 | 稳定 JSON 序列化 | 两个 Provider 接收一致、可测试的结构化内容 |
| 配置 | 不增加工具配置字段 | 本阶段工具集合、超时和限制固定，符合 YAGNI |
| 依赖注入 | Provider HTTP、工具交互、时间源和子进程启动均可替换 | 测试不访问真实网络，也不执行危险操作 |
| 兼容策略 | 保留 `stream_turn() -> Iterator[str]` 和现有 TUI 文本流 | 普通聊天路径及用户体验改动最小 |

## 设计自检

- **Spec 覆盖：** F1-F16 均已分配到 Provider、运行时、工具、工作区、执行器或 TUI 模块。
- **接口完整性：** 工具准备/执行、注册、确认、Provider 事件、回灌消息和运行时入口均已定义。
- **依赖方向：** Provider 基础类型与工具基础类型位于底层；具体 Provider 和具体工具依赖基础类型；运行时负责组合，不存在反向依赖。
- **范围一致：** 没有引入自动循环、并行调用、文件删除、网络工具或新配置项。
- **兼容性：** 原有配置查找、普通文本流、退出行为和密钥脱敏继续保留。
