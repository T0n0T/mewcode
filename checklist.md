# MewCode Basic Chat Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为。

## 实现完整性

- [ ] 启动 MewCode 后进入行式交互界面，并显示输入提示（验证：运行 `uv run python -m mewcode`，使用有效 mock 或测试配置，观察欢迎信息和输入提示）。
- [ ] 用户输入普通问题后，回复文本以多个片段逐步写入输出流（验证：运行 `uv run pytest tests/test_tui.py -k stream`，期望 fake runtime 的多个片段都被写出且触发 flush）。
- [ ] 同一进程内的后续请求包含此前用户消息和助手最终回复（验证：运行 `uv run pytest tests/test_runtime.py`，期望多轮历史断言通过）。
- [ ] 用户级 YAML 配置能加载当前唯一配置，并校验 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking`（验证：运行 `uv run pytest tests/test_config.py`，期望合法配置和字段校验测试通过）。
- [ ] `thinking` 字段省略时默认关闭，非布尔值时报可读配置错误（验证：运行 `uv run pytest tests/test_config.py -k thinking`）。
- [ ] 配置为 OpenAI 协议时，系统创建 OpenAI 后端并构造流式 Responses API 请求（验证：运行 `uv run pytest tests/test_providers.py -k openai`）。
- [ ] 配置为 Anthropic 协议时，系统创建 Anthropic 后端并构造流式 Messages API 请求（验证：运行 `uv run pytest tests/test_providers.py -k anthropic`）。
- [ ] Claude extended thinking 开启时，请求体包含 thinking 配置，但输出中没有 thinking 内容（验证：运行 `uv run pytest tests/test_providers.py -k anthropic`，检查 thinking delta 不被 yield）。
- [ ] 用户输入 `exit`、`quit` 或 Ctrl-D 后会话正常结束（验证：运行 `uv run pytest tests/test_tui.py -k exit`）。

## 集成

- [ ] CLI 启动链路能完成配置加载、Provider 创建、运行时创建和 TUI 启动（验证：运行 `uv run pytest tests/test_tui.py` 中 CLI main 集成用例，期望返回码正确）。
- [ ] TUI 只依赖统一 Provider 行为，不需要区分 OpenAI 与 Anthropic（验证：运行 `uv run pytest tests/test_runtime.py tests/test_tui.py`，使用 fake provider/runtime 均通过）。
- [ ] SSE 解析器支持 Provider 所需事件形态，包括事件名、JSON data、多行 data 和 `[DONE]`（验证：运行 `uv run pytest tests/test_sse.py`）。
- [ ] Provider 错误、配置错误和启动错误都会转成可展示错误信息（验证：运行 `uv run pytest tests/test_config.py tests/test_providers.py tests/test_tui.py -k error`）。
- [ ] 错误信息不泄露配置中的 API key（验证：运行 `uv run pytest tests/test_config.py tests/test_providers.py -k redaction`）。

## 编译与测试

- [ ] 项目依赖和测试工具可通过 `uv` 安装并运行（验证：运行 `uv run pytest --version`，期望输出 pytest 版本）。
- [ ] 全部单元测试通过（验证：运行 `uv run pytest`，期望全部通过）。
- [ ] Python 语法编译通过（验证：运行 `uv run python -m compileall mewcode tests`，期望无编译错误）。
- [ ] 命令入口可导入并执行（验证：运行 `uv run python -m mewcode`，配置缺失时应显示配置错误并返回非零，而不是导入错误或崩溃堆栈）。
- [ ] 改动范围符合任务文件清单（验证：运行 `git status --short`，确认新增/修改文件与 `task.md` 文件清单一致）。

## 端到端场景

- [ ] 场景 1：使用 OpenAI 配置启动，输入一条问题，终端逐步显示最终回复，然后输入 `exit` 正常退出（验证：使用 mock HTTP stream 或真实测试配置运行 CLI，观察流式输出和退出码 `0`）。
- [ ] 场景 2：使用 Anthropic 配置且 `thinking: true` 启动，输入一条问题，终端只显示最终回复，不显示 thinking 内容，然后输入 `quit` 正常退出（验证：使用 mock HTTP stream 或真实测试配置运行 CLI，观察输出不包含 thinking delta）。
- [ ] 场景 3：配置文件缺失时启动，终端显示包含配置路径的可读错误，进程返回非零（验证：临时指定空 HOME 或移走配置后运行 `uv run python -m mewcode`，观察错误和退出码）。
- [ ] 场景 4：同一会话连续提问两次，第二次请求携带第一轮用户问题和助手回复（验证：使用 fake provider 记录收到的 messages，运行两轮输入，检查第二轮历史包含前一轮完整对话）。
