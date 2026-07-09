# MewCode Basic Chat Plan

## 架构概览

MewCode 第一版采用轻量分层 CLI 架构：入口层负责启动程序，配置层负责加载和校验项目级或用户级 YAML，TUI 层负责终端交互，运行时层负责维护当前进程内的多轮会话历史，Provider 层负责屏蔽不同模型协议的请求与流式解析差异。

CLI 入口只做启动编排：加载配置、创建 Provider、启动交互式对话循环。它不直接处理 OpenAI 或 Anthropic 协议细节，避免后续新增后端时污染入口逻辑。

配置层默认按顺序查找 `./.mewcode/config.yaml` 和 `~/.mewcode/config.yaml`，读取第一个存在的唯一当前配置，并校验 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking`。其中 `thinking` 在 YAML 中可省略，省略时归一化为 `false`。配置层负责把缺失字段、未知协议、无效布尔值等问题转成可读错误，并保证错误信息不泄露 `api_key`。

TUI 层提供简单稳定的行式交互界面：显示猫猫文字画、当前配置摘要和 Claude Code 风格的输入/回复块，接收用户输入，识别退出命令，将用户消息交给运行时层，并把 Provider 返回的文本片段即时写入终端。第一版不做全屏布局。

运行时层维护当前进程内的消息列表。每轮对话先追加用户消息，再调用 Provider 流式生成回复；流式完成后，将完整 AI 最终回复追加到历史中，供下一轮请求使用。

Provider 层定义统一协议：接收会话消息和配置，返回一个可迭代的文本片段流。OpenAI Provider 和 Anthropic Provider 分别实现各自 HTTP 请求、SSE 解析、错误转换和最终文本过滤。TUI 和运行时只依赖统一 Provider 行为。

SSE 解析层负责从 HTTP 流中解析 `event:` / `data:` 形式的事件，向具体 Provider 暴露结构化事件。OpenAI Provider 只产出最终文本增量；Anthropic Provider 只产出 `text_delta`，忽略 thinking、signature、tool use 等非本阶段展示内容。

## 核心数据结构

### ProviderProtocol

```python
ProviderProtocol = Literal["openai", "anthropic"]
```

表示配置中的协议类型。第一版只接受 `openai` 和 `anthropic`，未知值在配置加载阶段报错。

### LLMConfig

```python
@dataclass(frozen=True)
class LLMConfig:
    name: str
    protocol: ProviderProtocol
    model: str
    base_url: str
    api_key: str = field(repr=False)
    thinking: bool = False
```

表示从当前生效配置文件加载后的唯一配置。`api_key` 不参与默认字符串展示，错误输出也必须脱敏。`thinking` 在配置文件中可省略，加载后统一为布尔值。

### ChatMessage

```python
@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str
```

表示会话历史中的一条消息。第一版只保留 `user` 和 `assistant` 两种角色，不引入 system、tool 或文件上下文消息。

### SSEEvent

```python
@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: dict[str, Any]
```

表示从 SSE HTTP 流中解析出的一条事件。Provider 只消费自己关心的事件，其余事件忽略或转成错误。

### MewCodeError

```python
class MewCodeError(Exception):
    user_message: str
```

所有可展示错误的基类。配置错误、Provider 错误、网络错误和 API 错误统一转成不泄露密钥的 `user_message`。

## 核心接口

### 配置加载

```python
def load_config(path: Path | None = None) -> LLMConfig
```

无显式路径时按 `./.mewcode/config.yaml`、`~/.mewcode/config.yaml` 的顺序读取 YAML；有显式路径时只读取该路径。校验字段，规范化 `base_url`，返回 `LLMConfig`。

### Provider 工厂

```python
def create_provider(config: LLMConfig) -> LLMProvider
```

根据 `config.protocol` 创建 `OpenAIProvider` 或 `AnthropicProvider`。

### Provider 统一接口

```python
class LLMProvider(Protocol):
    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        ...
```

接收完整会话历史，返回可展示的最终回复文本片段流。TUI 不知道具体后端协议。

### 会话运行时

```python
class ChatRuntime:
    def stream_turn(self, user_text: str) -> Iterator[str]:
        ...
```

负责追加用户消息、调用 Provider、收集完整助手回复，并在流式完成后追加助手消息。若流式中途失败，不把不完整助手回复写入历史。

### TUI 应用

```python
class ChatApp:
    def run(self) -> int:
        ...
```

负责欢迎信息、输入循环、退出命令、流式打印、错误展示和最终退出码。

## 模块设计

### CLI 入口模块

**职责：** 作为程序入口，完成启动编排。  
**对外接口：** `main() -> int`。  
**依赖：** 配置模块、Provider 工厂、TUI 模块。  
**覆盖需求：** F1、F4、F5、F9。

启动流程为：加载配置；根据配置创建 Provider；创建会话运行时；启动 TUI 输入循环；捕获可展示错误并返回非零退出码。

### 配置模块

**职责：** 查找、读取并校验项目级或用户级 YAML 配置。  
**对外接口：** `load_config(path: Path | None = None) -> LLMConfig`。  
**依赖：** 标准库路径处理、YAML 解析库。  
**覆盖需求：** F4、F5、F8、AC6、AC9。

配置模块只接受单个当前配置，不支持 profile。默认项目级配置优先生效，缺失时回退用户级配置；显式传入路径时不执行查找。字段缺失、字段类型错误、协议值未知、空字符串等问题统一转成配置错误。错误信息必须包含配置路径或默认查找路径和可修复提示，但不得包含 `api_key` 的值。

### Provider 基础模块

**职责：** 定义跨后端共用的数据结构、协议接口、错误类型和工厂。  
**对外接口：** `LLMProvider`、`create_provider()`、`ChatMessage`、`MewCodeError`。  
**依赖：** 配置模块中的 `LLMConfig`。  
**覆盖需求：** F5、F6、AC7。

该模块是 TUI 与具体模型协议之间的边界。后续新增 Provider 时，只需要新增实现并扩展工厂，不改 TUI 的流式显示逻辑。

### SSE 解析模块

**职责：** 解析 HTTP 响应中的 Server-Sent Events。  
**对外接口：** `iter_sse_events(response: httpx.Response) -> Iterator[SSEEvent]`。  
**依赖：** HTTP 客户端返回的字节/文本流。  
**覆盖需求：** F2、F6、N2。

解析模块处理 `event:`、`data:`、空行分隔、多行 data 和 `[DONE]` 终止标记。它只做通用 SSE 解析，不包含 OpenAI 或 Anthropic 的业务事件判断。

### OpenAI Provider 模块

**职责：** 调用 OpenAI Responses API，并把 OpenAI 流式事件转换为最终回复文本片段。  
**对外接口：** `OpenAIProvider.stream_chat(messages)`。  
**依赖：** Provider 基础模块、SSE 解析模块、HTTP 客户端。  
**覆盖需求：** F2、F3、F6、F8、AC2、AC3、AC4、AC7、AC9。

请求使用配置中的 `base_url`、`model` 和 `api_key`，把会话历史转换成 OpenAI Responses API 输入格式，设置流式响应，并只产出最终文本增量事件。HTTP 错误、API 错误事件、连接错误和解析错误统一转成可展示 Provider 错误；连接错误需要包含目标 URL 和检查 Provider 服务地址的提示。

### Anthropic Provider 模块

**职责：** 调用 Anthropic Messages API，并把 Claude 流式事件转换为最终回复文本片段。  
**对外接口：** `AnthropicProvider.stream_chat(messages)`。  
**依赖：** Provider 基础模块、SSE 解析模块、HTTP 客户端。  
**覆盖需求：** F2、F3、F6、F7、F8、AC2、AC3、AC5、AC7、AC8、AC9。

请求使用配置中的 `base_url`、`model`、`api_key` 和 `thinking`。Messages API 请求使用固定默认输出上限；开启 thinking 时，使用 Provider 内部固定 thinking 配置并要求后端省略 thinking 内容。流式解析只产出文本 delta，忽略 thinking 和签名事件。HTTP 错误、API 错误事件和解析错误统一转成可展示 Provider 错误。

### 会话运行时模块

**职责：** 管理当前进程内的多轮会话历史。  
**对外接口：** `ChatRuntime.stream_turn(user_text)`。  
**依赖：** Provider 基础接口。  
**覆盖需求：** F2、F3、F8、AC2、AC3。

运行时在每轮请求前追加用户消息，流式收集助手回复片段。只有当 Provider 正常结束时，才把完整助手回复加入历史；如果请求失败，保留用户消息并向 TUI 抛出可展示错误，让用户决定是否继续。

### TUI 模块

**职责：** 提供行式交互界面和流式输出体验。  
**对外接口：** `ChatApp.run() -> int`。  
**依赖：** 会话运行时、错误类型。  
**覆盖需求：** F1、F2、F8、F9、AC1、AC2、AC9、AC10。

TUI 显示猫猫文字画、配置名、协议名和模型名，循环读取用户输入。空输入直接忽略；退出命令使用 `exit`、`quit` 或 Ctrl-D。收到回复片段时立即写入标准输出并刷新。

## 模块交互

启动链路：

```text
main()
  -> load_config() 查找 ./.mewcode/config.yaml 或 ~/.mewcode/config.yaml
  -> create_provider(config)
  -> ChatRuntime(provider)
  -> ChatApp(runtime, config).run()
```

单轮对话链路：

```text
用户输入
  -> ChatApp 识别非空且非退出输入
  -> ChatRuntime.stream_turn(user_text)
  -> 追加 user ChatMessage 到历史
  -> LLMProvider.stream_chat(history)
  -> OpenAIProvider 或 AnthropicProvider 发起 HTTP SSE 请求
  -> iter_sse_events(response) 解析事件
  -> Provider 过滤并 yield 最终文本片段
  -> ChatApp 即时打印并 flush
  -> ChatRuntime 收集完整助手回复
  -> 流式完成后追加 assistant ChatMessage 到历史
  -> ChatApp 回到输入提示
```

错误链路：

```text
配置错误 / 协议错误 / HTTP 错误 / API 错误 / SSE 解析错误
  -> 转成 MewCodeError(user_message)
  -> CLI 启动阶段错误：打印错误并返回非零退出码
  -> 对话阶段错误：TUI 打印错误，保留输入循环
```

## 文件组织

```text
mewcode/
├── __init__.py
├── __main__.py             — `python -m mewcode` 入口
├── cli.py                  — main 启动编排
├── config.py               — YAML 配置查找、加载、字段校验、LLMConfig
├── errors.py               — MewCodeError 及配置/Provider 错误
├── runtime.py              — ChatRuntime，多轮历史管理
├── tui.py                  — ChatApp，行式交互和流式打印
└── providers/
    ├── __init__.py         — create_provider 导出
    ├── base.py             — ChatMessage、LLMProvider、ProviderProtocol
    ├── sse.py              — SSEEvent、iter_sse_events
    ├── openai.py           — OpenAIProvider
    └── anthropic.py        — AnthropicProvider

tests/
├── test_config.py          — 配置加载、字段校验、密钥脱敏
├── test_sse.py             — SSE 解析边界
├── test_runtime.py         — 多轮历史和失败行为
├── test_providers.py       — Provider 请求构造和事件过滤
└── test_tui.py             — 退出命令、空输入、流式打印行为

main.py                     — 兼容当前脚本入口，转调 mewcode.cli.main
AGENTS.md                   — 仓库协作说明
config.yaml.example         — 示例配置文件
pyproject.toml              — 项目元数据、依赖、命令入口、测试配置
README.md                   — 最小使用说明和配置样例
docs/spec.md                — 已批准需求
docs/plan.md                — 本设计文档
docs/task.md                — 实施任务清单
docs/checklist.md           — 验收清单
```

`pyproject.toml` 会增加命令入口：

```toml
[project.scripts]
mewcode = "mewcode.cli:main"
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 开发语言 | Python 3.13 | 与现有项目一致，适合快速实现 CLI、YAML 配置、HTTP SSE 和测试。 |
| TUI 形态 | 带猫猫文字画的 Claude Code 风格行式交互界面 | 满足第一版纯对话需求，避免全屏 TUI 带来的额外状态管理，同时让终端体验更清晰。 |
| 配置位置 | 先 `./.mewcode/config.yaml`，后 `~/.mewcode/config.yaml` | 项目级配置便于不同项目使用不同模型；用户级配置作为跨目录默认值。 |
| 配置模型 | 单个当前配置 | 与需求一致，降低第一版切换规则复杂度。 |
| `thinking` 缺省值 | YAML 可省略，内部默认为 `false` | 对齐初始需求中的可选字段，同时保证运行时总有明确布尔值。 |
| Anthropic 输出上限 | Provider 内部固定默认值 | 配置只包含六个字段；第一版不扩展配置面。 |
| YAML 解析 | `PyYAML` | 依赖轻、成熟，足够处理第一版固定字段配置。 |
| HTTP 客户端 | `httpx` 同步客户端 | 支持流式响应，API 清晰；同步实现更贴合行式 CLI，降低第一版复杂度。 |
| OpenAI 协议 | Responses API + SSE | 当前 OpenAI 推荐的统一响应接口，天然支持流式事件和后续 agent 能力扩展。 |
| Anthropic 协议 | Messages API + SSE | Claude 官方消息接口，支持 streaming 和 extended thinking。 |
| Claude thinking 展示 | 请求 thinking 但省略展示 | 满足启用 extended thinking 的需求，同时保持 TUI 只展示最终回复。 |
| Provider 抽象 | `stream_chat(messages) -> Iterator[str]` | TUI 只关心可显示文本片段，后端协议差异留在 Provider 内部。 |
| 会话历史 | 进程内列表 | 满足多轮对话，不引入持久化或长期记忆。 |
| 错误模型 | 统一可展示错误 `MewCodeError` | 启动错误和对话错误都能转成用户可理解提示，并集中处理密钥脱敏。 |
| 测试策略 | 单元测试 + mocked HTTP stream | 不依赖真实 API key 即可验证配置、SSE、Provider 事件过滤、历史管理和 TUI 行为。 |

## 需求覆盖

- F1: `ChatApp.run()` 和 CLI 入口覆盖。
- F2: Provider 流式接口、SSE 解析、TUI flush 覆盖。
- F3: `ChatRuntime` 历史管理覆盖。
- F4: `config.py` 的默认查找顺序和 `LLMConfig` 覆盖。
- F5: `ProviderProtocol`、配置校验、`create_provider()` 覆盖。
- F6: `LLMProvider.stream_chat()` 覆盖。
- F7: `AnthropicProvider` thinking 请求和事件过滤覆盖。
- F8: `MewCodeError`、配置/Provider/TUI 错误链路覆盖。
- F9: TUI 退出命令覆盖。

## 依赖关系

依赖关系无环：`cli -> config/providers/runtime/tui`，`tui -> runtime/errors`，`runtime -> providers.base`，具体 Provider 只依赖 `providers.base/sse`、`config` 和 HTTP 客户端。没有模块需要反向依赖 TUI。

## 参考文档

- OpenAI streaming responses: https://platform.openai.com/docs/guides/streaming-responses
- OpenAI Responses create: https://platform.openai.com/docs/api-reference/responses/create
- Anthropic streaming messages: https://platform.claude.com/docs/en/build-with-claude/streaming
- Anthropic extended thinking: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
