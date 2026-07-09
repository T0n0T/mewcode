# MewCode Basic Chat Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|------|------|------|
| 新建 | `mewcode/__init__.py` | 包初始化与版本信息 |
| 新建 | `mewcode/__main__.py` | 支持 `python -m mewcode` |
| 新建 | `mewcode/cli.py` | CLI 启动编排 |
| 新建 | `mewcode/config.py` | YAML 配置加载、字段校验、`LLMConfig` |
| 新建 | `mewcode/errors.py` | 可展示错误类型 |
| 新建 | `mewcode/runtime.py` | 多轮会话历史与单轮流式运行 |
| 新建 | `mewcode/tui.py` | 行式交互界面与流式打印 |
| 新建 | `mewcode/providers/__init__.py` | Provider 工厂导出 |
| 新建 | `mewcode/providers/base.py` | `ChatMessage`、Provider 协议、协议类型 |
| 新建 | `mewcode/providers/sse.py` | SSE 事件结构与解析器 |
| 新建 | `mewcode/providers/openai.py` | OpenAI Responses API Provider |
| 新建 | `mewcode/providers/anthropic.py` | Anthropic Messages API Provider |
| 新建 | `tests/test_config.py` | 配置加载与脱敏测试 |
| 新建 | `tests/test_sse.py` | SSE 解析测试 |
| 新建 | `tests/test_runtime.py` | 会话历史测试 |
| 新建 | `tests/test_providers.py` | Provider 请求构造与事件过滤测试 |
| 新建 | `tests/test_tui.py` | TUI 输入输出测试 |
| 修改 | `main.py` | 兼容旧入口，转调新 CLI |
| 修改 | `pyproject.toml` | 增加依赖、命令入口、pytest 配置 |
| 修改 | `README.md` | 增加最小使用说明和配置样例 |

## T1: 初始化项目依赖和命令入口配置

**文件：** `pyproject.toml`  
**依赖：** 无  
**步骤：**
1. 增加运行时依赖：`httpx`、`PyYAML`。
2. 增加测试依赖：`pytest`。
3. 增加命令入口 `mewcode = "mewcode.cli:main"`。
4. 增加基础 pytest 配置，测试目录指向 `tests`。

**验证：** 运行 `uv run pytest --version`，期望 pytest 能正常输出版本信息。

## T2: 创建包结构和入口文件

**文件：** `mewcode/__init__.py`、`mewcode/__main__.py`、`mewcode/cli.py`、`mewcode/providers/__init__.py`、`main.py`  
**依赖：** T1  
**步骤：**
1. 创建 `mewcode` 包和 `mewcode.providers` 子包。
2. 在 `mewcode/__init__.py` 暴露版本信息。
3. 在 `mewcode/cli.py` 创建可导入的 `main() -> int` 临时入口，后续 T12 完成启动编排。
4. 在 `mewcode/__main__.py` 调用 CLI 主入口。
5. 修改 `main.py`，保留兼容入口并转调 `mewcode.cli.main`。
6. 在 `mewcode/providers/__init__.py` 暂时导出 Provider 工厂占位接口，后续任务补实现。

**验证：** 运行 `uv run python -m mewcode`，期望入口模块可导入并正常退出，不出现包导入错误。

## T3: 实现统一错误类型

**文件：** `mewcode/errors.py`  
**依赖：** T2  
**步骤：**
1. 定义 `MewCodeError`，保存 `user_message`。
2. 定义 `ConfigError` 和 `ProviderError`。
3. 确保 `str(error)` 返回可展示消息。
4. 提供简单脱敏辅助逻辑，避免错误信息包含密钥原文。

**验证：** 运行 `uv run python -c "from mewcode.errors import MewCodeError; print(MewCodeError('ok'))"`，期望输出 `ok`。

## T4: 实现 Provider 基础类型和接口

**文件：** `mewcode/providers/base.py`  
**依赖：** T3  
**步骤：**
1. 定义 `ProviderProtocol = Literal["openai", "anthropic"]`。
2. 定义 `ChatMessage` 数据结构。
3. 定义 `LLMProvider` 协议，包含 `stream_chat(messages)`。
4. 保持该模块不依赖具体 Provider 实现，避免依赖环。

**验证：** 运行 `uv run python -c "from mewcode.providers.base import ChatMessage; print(ChatMessage('user', 'hi'))"`，期望正常输出对象表示。

## T5: 实现配置加载和校验

**文件：** `mewcode/config.py`  
**依赖：** T3、T4  
**步骤：**
1. 定义 `CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"`。
2. 定义 `LLMConfig` 数据结构，包含 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking`。
3. 实现 YAML 文件读取，缺失文件时报 `ConfigError` 并提示路径。
4. 校验必需字段 `name`、`protocol`、`model`、`base_url`、`api_key`。
5. 将可选字段 `thinking` 缺省归一化为 `False`，并校验必须为布尔值。
6. 校验 `protocol` 只能是 `openai` 或 `anthropic`。
7. 规范化 `base_url`，去掉末尾 `/`。
8. 确保错误消息不包含 `api_key` 原文。

**验证：** 运行 `uv run pytest tests/test_config.py`，期望配置读取、字段缺失、未知协议、thinking 缺省和密钥脱敏测试通过。

## T6: 实现 SSE 通用解析器

**文件：** `mewcode/providers/sse.py`  
**依赖：** T4  
**步骤：**
1. 定义 `SSEEvent` 数据结构。
2. 实现按行解析 SSE：支持 `event:`、`data:`、空行提交事件。
3. 支持多行 `data:` 合并为一段文本。
4. 遇到 `data: [DONE]` 时终止迭代。
5. 将 JSON data 解析为字典；非 JSON data 转成解析错误。
6. 忽略 SSE 注释行。
7. 将底层读取异常转成 `ProviderError`。

**验证：** 运行 `uv run pytest tests/test_sse.py`，期望单事件、多行 data、`[DONE]`、非 JSON 错误测试通过。

## T7: 实现 Provider 工厂

**文件：** `mewcode/providers/__init__.py`  
**依赖：** T4、T5  
**步骤：**
1. 实现 `create_provider(config)`。
2. 当 `config.protocol == "openai"` 时返回 `OpenAIProvider`。
3. 当 `config.protocol == "anthropic"` 时返回 `AnthropicProvider`。
4. 对未知协议抛出 `ProviderError`。
5. 避免在模块导入时执行网络请求。

**验证：** 运行 `uv run pytest tests/test_providers.py -k factory`，期望 OpenAI、Anthropic 和未知协议工厂测试通过。

## T8: 实现 OpenAI Provider

**文件：** `mewcode/providers/openai.py`  
**依赖：** T4、T5、T6  
**步骤：**
1. 定义 `OpenAIProvider`，保存 `LLMConfig` 和可注入 HTTP 客户端。
2. 将 `ChatMessage` 历史转换为 Responses API 输入。
3. 向 `{base_url}/responses` 发起 POST 请求。
4. 设置认证头 `Authorization: Bearer <api_key>`。
5. 请求体包含 `model`、`input`、`stream: true`。
6. 使用 `iter_sse_events` 解析流式响应。
7. 只对 OpenAI 最终文本增量事件产出文本片段。
8. 遇到错误事件、HTTP 非 2xx、网络异常或解析异常时抛出 `ProviderError`。
9. 确保错误信息不包含 `api_key`。

**验证：** 运行 `uv run pytest tests/test_providers.py -k openai`，期望请求 URL、请求头、请求体、文本 delta 过滤和错误脱敏测试通过。

## T9: 实现 Anthropic Provider

**文件：** `mewcode/providers/anthropic.py`  
**依赖：** T4、T5、T6  
**步骤：**
1. 定义 `AnthropicProvider`，保存 `LLMConfig` 和可注入 HTTP 客户端。
2. 将 `ChatMessage` 历史转换为 Messages API 请求消息。
3. 向 `{base_url}/messages` 发起 POST 请求。
4. 设置认证头 `x-api-key` 和 `anthropic-version`。
5. 请求体包含 `model`、`messages`、`stream: true` 和内部固定 `max_tokens`。
6. 当 `thinking` 为 `True` 时加入 extended thinking 配置，并要求省略 thinking 展示内容。
7. 使用 `iter_sse_events` 解析流式响应。
8. 只对 Claude 文本增量事件产出文本片段，忽略 thinking、signature 和非文本事件。
9. 遇到错误事件、HTTP 非 2xx、网络异常或解析异常时抛出 `ProviderError`。
10. 确保错误信息不包含 `api_key`。

**验证：** 运行 `uv run pytest tests/test_providers.py -k anthropic`，期望请求 URL、请求头、请求体、thinking 请求、文本 delta 过滤和错误脱敏测试通过。

## T10: 实现会话运行时

**文件：** `mewcode/runtime.py`  
**依赖：** T4、T8、T9  
**步骤：**
1. 定义 `ChatRuntime`，保存 Provider 和消息历史列表。
2. 实现 `stream_turn(user_text)`。
3. 每轮先追加用户消息。
4. 调用 Provider 的 `stream_chat(history)` 并逐片段向外 yield。
5. 收集完整助手回复。
6. Provider 正常结束后追加助手消息。
7. Provider 失败时不追加不完整助手回复，并继续保留用户消息。
8. 提供只读方式便于测试检查历史。

**验证：** 运行 `uv run pytest tests/test_runtime.py`，期望多轮历史、流式透传、失败不追加助手消息测试通过。

## T11: 实现行式 TUI

**文件：** `mewcode/tui.py`  
**依赖：** T10  
**步骤：**
1. 定义 `ChatApp`，接收 `ChatRuntime`、`LLMConfig`、输入流和输出流。
2. 启动时打印 MewCode 欢迎信息、当前配置名和协议名。
3. 循环显示用户输入提示。
4. 忽略空输入。
5. 识别 `exit`、`quit` 退出命令。
6. 捕获 Ctrl-D 并正常退出。
7. 对每轮输入调用 `runtime.stream_turn(user_text)`。
8. 对每个回复片段立即写入输出流并 flush。
9. 每轮回复结束后打印换行。
10. 捕获 `MewCodeError`，打印可展示错误并继续输入循环。
11. `run()` 正常结束返回 `0`。

**验证：** 运行 `uv run pytest tests/test_tui.py`，期望欢迎信息、退出命令、空输入、流式 flush 和对话阶段错误测试通过。

## T12: 实现 CLI 启动编排

**文件：** `mewcode/cli.py`、`mewcode/__main__.py`、`main.py`  
**依赖：** T5、T7、T10、T11  
**步骤：**
1. 在 `mewcode/cli.py` 实现 `main() -> int`。
2. 加载用户级配置。
3. 创建 Provider。
4. 创建 `ChatRuntime`。
5. 创建并运行 `ChatApp`。
6. 捕获启动阶段 `MewCodeError`，向 stderr 输出可展示错误并返回非零退出码。
7. 在 `mewcode/__main__.py` 使用 `raise SystemExit(main())`。
8. 在 `main.py` 使用同样方式转调 CLI 主入口。

**验证：** 运行 `uv run python -m mewcode` 且临时移走配置文件，期望输出配置缺失错误并以非零状态退出。

## T13: 编写配置与 SSE 测试

**文件：** `tests/test_config.py`、`tests/test_sse.py`  
**依赖：** T5、T6  
**步骤：**
1. 在配置测试中覆盖合法配置加载。
2. 覆盖 `thinking` 省略时为 `False`。
3. 覆盖缺失必需字段。
4. 覆盖未知协议。
5. 覆盖 `thinking` 非布尔值。
6. 覆盖错误信息不包含密钥原文。
7. 在 SSE 测试中覆盖单事件、多行 data、注释行、`[DONE]` 和非 JSON data。

**验证：** 运行 `uv run pytest tests/test_config.py tests/test_sse.py`，期望全部通过。

## T14: 编写 Provider 与运行时测试

**文件：** `tests/test_providers.py`、`tests/test_runtime.py`  
**依赖：** T7、T8、T9、T10  
**步骤：**
1. 用 mock HTTP 客户端覆盖 Provider 工厂。
2. 覆盖 OpenAI 请求 URL、认证头、请求体和流式文本事件过滤。
3. 覆盖 OpenAI 错误事件、HTTP 错误和密钥脱敏。
4. 覆盖 Anthropic 请求 URL、认证头、请求体和流式文本事件过滤。
5. 覆盖 Anthropic thinking 开启时请求体包含 thinking 配置且不输出 thinking delta。
6. 覆盖 Anthropic 错误事件、HTTP 错误和密钥脱敏。
7. 覆盖 `ChatRuntime` 多轮历史、片段透传和失败时不追加助手消息。

**验证：** 运行 `uv run pytest tests/test_providers.py tests/test_runtime.py`，期望全部通过。

## T15: 编写 TUI 和端到端 CLI 测试

**文件：** `tests/test_tui.py`  
**依赖：** T11、T12  
**步骤：**
1. 使用可控输入流模拟用户输入普通问题后退出。
2. 使用 fake runtime 返回多个文本片段，验证输出中逐段出现。
3. 验证空输入不会触发 runtime。
4. 验证 `exit`、`quit` 和 Ctrl-D 正常结束。
5. 验证 runtime 抛出 `MewCodeError` 时 TUI 打印错误并继续循环。
6. 通过 CLI main 的依赖注入或 monkeypatch 验证启动阶段配置错误返回非零退出码。

**验证：** 运行 `uv run pytest tests/test_tui.py`，期望全部通过。

## T16: 更新 README 使用说明

**文件：** `README.md`  
**依赖：** T12  
**步骤：**
1. 写明 MewCode 第一版能力边界：纯对话、无 tool use、无文件操作。
2. 写明启动方式：`uv run mewcode`、`uv run python -m mewcode`。
3. 提供 OpenAI 配置样例。
4. 提供 Anthropic 配置样例。
5. 说明 `thinking` 可省略，默认 `false`。
6. 说明退出命令：`exit`、`quit` 或 Ctrl-D。
7. 提醒不要把真实 API key 提交到仓库。

**验证：** 运行 `sed -n '1,220p' README.md`，期望能看到启动方式、配置路径、两类配置样例和能力边界。

## T17: 全量验证与格式检查

**文件：** 全项目  
**依赖：** T1-T16  
**步骤：**
1. 运行全部测试。
2. 运行 `uv run python -m mewcode` 的配置缺失启动检查。
3. 运行 `uv run python -m compileall mewcode tests` 检查语法。
4. 检查 `git status --short`，确认改动范围符合 task 文件清单。

**验证：** `uv run pytest`、`uv run python -m compileall mewcode tests` 通过；配置缺失场景返回非零并显示清晰错误。

## 执行顺序

```text
T1
 -> T2
 -> T3
 -> T4
 -> T5
 -> T6
 -> T7
 -> T8
 -> T9
 -> T10
 -> T11
 -> T12
 -> T13
 -> T14
 -> T15
 -> T16
 -> T17
```

T13-T15 是测试补强任务，依赖对应实现后可局部并行；实际开发时仍按顺序跑验证，确保每步证据清楚。
