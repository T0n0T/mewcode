# MewCode Tool System Checklist

> 每项都通过运行测试、执行命令或观察终端行为验证；实现完成后逐项记录实际证据。

## 验收记录（2026-07-12）

- [x] 全量测试：`uv run pytest -q`，实际结果 `93 passed`。
- [x] 编译检查：`uv run python -m compileall -q mewcode tests`，实际返回 `0`。
- [x] 依赖锁定：`uv sync --all-groups --locked`，实际完成解析与审计。
- [x] 启动检查：模块入口和 console script 在仓库外、空 HOME 下均返回 `1`，只显示配置缺失错误且无堆栈。
- [x] 端到端聚焦验证：读取工具回灌、写入拒绝、工作区逃逸共 `3 passed`；双 Provider 多 slot 共 `2 passed`；CLI、状态与确认共 `5 passed`。
- [x] 交付检查：`git diff --check` 返回 `0`，敏感信息扫描无匹配，`.mewcode/config.yaml` 与示例配置均未改动。

下方条目保留为需求级追踪清单；本次实际执行证据以上述命令及全量测试为准。

## 工具定义与注册

- [ ] 六个核心工具以固定名称 `read_file`、`write_file`、`edit_file`、`run_command`、`glob_files`、`search_code` 注册，且可按名称查找（验证：运行 `uv run pytest tests/test_tool_registry.py -k defaults`，期望六个名称完整且顺序稳定）。
- [ ] 每个工具都提供名称、描述和对象类型 JSON 参数 Schema，且拒绝未声明参数（验证：运行 `uv run pytest tests/test_tool_registry.py -k schema`，期望 Schema 校验用例全部通过）。
- [ ] 空名称、无效 Schema 和重复名称均不能注册（验证：运行 `uv run pytest tests/test_tool_registry.py -k "register or duplicate or schema"`，期望拒绝用例全部通过）。
- [ ] 成功、错误、拒绝、超时及截断结果均可稳定序列化为模型可接收的 JSON（验证：运行 `uv run pytest tests/test_tool_registry.py -k result`，期望各状态结构断言通过）。
- [ ] OpenAI 与 Anthropic 均能从同一组统一定义生成各自协议的六个工具描述（验证：运行 `uv run pytest tests/test_providers.py -k "tools and (openai or anthropic)"`，期望两种请求体断言通过）。

## 文件工具

- [ ] 读取工作区内 UTF-8 文件会返回相对路径、内容、总行数和实际行范围（验证：运行 `uv run pytest tests/test_file_tools.py -k "read_file and success"`）。
- [ ] 已知路径指向 `.gitignore` 忽略文件时仍可读取（验证：运行 `uv run pytest tests/test_file_tools.py -k "read_file and ignored"`）。
- [ ] 缺失文件、目录、二进制文件和无效 UTF-8 文件均返回结构化错误，不显示内部堆栈（验证：运行 `uv run pytest tests/test_file_tools.py -k "read_file and error"`）。
- [ ] 写文件可新建 UTF-8 文件并自动创建缺失父目录（验证：运行 `uv run pytest tests/test_file_tools.py -k "write_file and new_file"`）。
- [ ] 写文件可完整覆盖已有文件，执行前显示目标路径与 diff，确认前不产生文件或目录（验证：运行 `uv run pytest tests/test_file_tools.py -k "write_file and (prepare or overwrite)"`）。
- [ ] 预览后文件或父目录状态发生变化时写入被拒绝，外部变化保持不变（验证：运行 `uv run pytest tests/test_file_tools.py -k "write_file and conflict"`）。
- [ ] 改文件在原文恰好出现一次时显示准确 diff，并只替换该处（验证：运行 `uv run pytest tests/test_file_tools.py -k "edit_file and success"`）。
- [ ] 改文件遇到零匹配或多匹配时返回不同的明确错误，文件内容不变（验证：运行 `uv run pytest tests/test_file_tools.py -k "edit_file and (not_found or not_unique)"`）。
- [ ] 写入和修改采用完整 UTF-8 写入，失败或冲突后不留下临时文件或半写入文件（验证：运行 `uv run pytest tests/test_file_tools.py -k "atomic or cleanup"`）。

## 搜索工具

- [ ] 文件查找支持工作区相对 glob 模式，并返回稳定排序的相对文件路径（验证：运行 `uv run pytest tests/test_search_tools.py -k "glob_files and basic"`）。
- [ ] 文件查找始终排除 `.git` 并遵循 `.gitignore`，包括否定与通配规则（验证：运行 `uv run pytest tests/test_search_tools.py -k "glob_files and ignore"`）。
- [ ] 代码搜索默认按字面量查找，返回相对路径、1 基行号和匹配行内容（验证：运行 `uv run pytest tests/test_search_tools.py -k "search_code and literal"`）。
- [ ] 代码搜索支持正则和路径模式过滤，无效正则返回结构化错误（验证：运行 `uv run pytest tests/test_search_tools.py -k "search_code and regex"`）。
- [ ] 代码搜索跳过 `.git`、忽略文件、二进制文件和无效 UTF-8 文件，并报告跳过数量（验证：运行 `uv run pytest tests/test_search_tools.py -k "search_code and skipped"`）。

## 命令工具

- [ ] 命令预览原样展示完整 shell 命令，确认前不会启动进程（验证：运行 `uv run pytest tests/test_command_tool.py -k prepare`）。
- [ ] 确认后命令以 MewCode 启动目录为工作目录，并支持管道、重定向和条件连接（验证：运行 `uv run pytest tests/test_command_tool.py -k "execute or shell_syntax"`）。
- [ ] 命令结果包含退出码、标准输出和标准错误；非零退出作为结构化错误返回但保留三项数据（验证：运行 `uv run pytest tests/test_command_tool.py -k exit_code`）。
- [ ] 命令默认超时为 30 秒，接受不超过 300 秒的正数设置，并拒绝无效设置（验证：运行 `uv run pytest tests/test_command_tool.py -k "timeout and validation"`）。
- [ ] 命令超时后终止整个进程组，不留下继续运行的子进程（验证：运行 `uv run pytest tests/test_command_tool.py -k timeout`，并确认用例检查子进程已退出）。
- [ ] stdout 或 stderr 含无效 UTF-8 时返回编码错误，不以替换字符静默继续（验证：运行 `uv run pytest tests/test_command_tool.py -k encoding`）。

## 工作区与确认安全

- [ ] 文件工具拒绝绝对路径、任何包含 `..` 的路径和指向工作区外的文件符号链接（验证：运行 `uv run pytest tests/test_workspace.py -k "existing_path and escape"`）。
- [ ] 新建文件路径即使父目录尚不存在也保持在工作区内；已有父目录符号链接不能造成逃逸（验证：运行 `uv run pytest tests/test_workspace.py -k create_path`）。
- [ ] 安全遍历不跟随目录符号链接到工作区外，并能在截止时间到达时停止（验证：运行 `uv run pytest tests/test_workspace.py -k walk`）。
- [ ] 每次写文件、改文件和执行命令都单独请求确认，只有 `y` 或 `yes` 批准（验证：运行 `uv run pytest tests/test_tui.py -k confirm`）。
- [ ] 用户拒绝后目标文件和命令副作用均不存在，模型收到 `rejected` 结构化结果（验证：运行 `uv run pytest tests/test_tool_executor.py tests/test_file_tools.py tests/test_command_tool.py -k rejected`）。
- [ ] 读取、找文件和搜内容无需确认即可执行（验证：运行 `uv run pytest tests/test_tool_registry.py tests/test_tool_executor.py -k "defaults or no_confirmation"`）。
- [ ] 普通工具使用固定 30 秒截止时间；到期返回 `timeout` 而非导致会话异常退出（验证：运行 `uv run pytest tests/test_tool_executor.py tests/test_workspace.py -k timeout`）。

## 错误与输出限制

- [ ] 未知工具、参数错误、路径越界、编码错误、冲突、拒绝、超时和执行异常均转换为统一结构化结果（验证：运行 `uv run pytest tests/test_tool_executor.py tests/test_file_tools.py tests/test_command_tool.py -k "error or rejected or timeout or conflict"`）。
- [ ] 参数校验错误指出具体字段位置，且不会调用工具的准备或执行方法（验证：运行 `uv run pytest tests/test_tool_executor.py -k arguments`）。
- [ ] 读取结果超过 50,000 字符时只返回限定内容，并报告原始量、返回量和缩小范围提示（验证：运行 `uv run pytest tests/test_file_tools.py -k truncated`）。
- [ ] 文件查找超过 1,000 条、内容搜索超过 500 条时返回稳定前缀及完整截断元数据（验证：运行 `uv run pytest tests/test_search_tools.py -k truncated`）。
- [ ] 命令 stdout 和 stderr 各自超过 50,000 字符时独立截断并报告各自原始量（验证：运行 `uv run pytest tests/test_command_tool.py -k truncated`）。
- [ ] API key 出现在参数、预览、结果、异常或 Provider 错误中时都会脱敏（验证：运行 `uv run pytest tests/test_tool_executor.py tests/test_tui.py tests/test_providers.py -k redaction`）。

## Provider 与运行时集成

- [ ] OpenAI 能把拆分的调用 ID、工具名称和 JSON 参数增量归并为同一工具调用（验证：运行 `uv run pytest tests/test_providers.py -k "openai and tool_delta"`）。
- [ ] Anthropic 能把 `tool_use` 与多个参数增量归并为同一工具调用（验证：运行 `uv run pytest tests/test_providers.py -k "anthropic and tool_delta"`）。
- [ ] 两种 Provider 的文本增量继续即时显示，响应完成时保存可回放的完整协议状态（验证：运行 `uv run pytest tests/test_providers.py -k "text_delta or completed"`）。
- [ ] 工具结果能按调用 ID 转换为 OpenAI 函数结果和 Anthropic `tool_result`，并在下一请求中回放（验证：运行 `uv run pytest tests/test_providers.py -k feedback`）。
- [ ] 不完整 JSON、数组或标量工具参数不会执行工具，并回灌 `invalid_tool_arguments`（验证：运行 `uv run pytest tests/test_runtime.py -k invalid_arguments`）。
- [ ] 无工具调用时只请求模型一次，普通多轮文本历史行为保持不变（验证：运行 `uv run pytest tests/test_runtime.py -k plain`）。
- [ ] 一个有效工具调用只执行一次，结果回灌后只再请求一次最终回答（验证：运行 `uv run pytest tests/test_runtime.py -k "single_tool or final_response"`）。
- [ ] 首次响应包含多个工具调用时全部不执行，每个调用收到关联 ID 的限制错误（验证：运行 `uv run pytest tests/test_runtime.py -k multiple_tool_calls`）。
- [ ] 第二次响应再次调用工具时不执行、不发起第三次请求，并显示“本轮工具额度已用完”（验证：运行 `uv run pytest tests/test_runtime.py tests/test_tui.py -k tool_budget`）。
- [ ] Provider 流中途失败、第二次违规调用或解析失败不会向历史写入不可回放的残缺助手消息（验证：运行 `uv run pytest tests/test_runtime.py -k "incomplete or history"`）。

## 终端与 CLI 集成

- [ ] 工具运行时显示工具名称、关键参数和成功、错误、拒绝或超时状态（验证：运行 `uv run pytest tests/test_tui.py -k tool_status`）。
- [ ] 读取、glob 和搜索的完整结果只回灌模型，不直接刷到终端（验证：运行 `uv run pytest tests/test_tui.py -k hidden_result`）。
- [ ] 命令确认显示完整命令，文件确认显示目标路径与 diff（验证：运行 `uv run pytest tests/test_tui.py -k preview`）。
- [ ] CLI 在启动时固定当前目录为工作区，并装配六工具注册中心、执行器、交互端口、Provider 和运行时（验证：运行 `uv run pytest tests/test_tui.py -k cli`）。
- [ ] OpenAI 和 Anthropic 使用相同的工具系统装配路径，切换协议不改变确认及终端交互方式（验证：运行 `uv run pytest tests/test_tui.py tests/test_providers.py -k "cli or uniform"`）。
- [ ] 配置查找优先级、退出命令、普通聊天流式输出和错误继续行为保持可用（验证：运行 `uv run pytest tests/test_config.py tests/test_runtime.py tests/test_tui.py`）。

## 编译与测试

- [ ] 新增依赖可由 `uv` 从锁文件安装（验证：运行 `uv sync --all-groups`，期望成功且 `uv.lock` 无未同步提示）。
- [ ] 全部单元与集成测试通过（验证：运行 `uv run pytest`，期望零失败）。
- [ ] 项目和测试语法编译通过（验证：运行 `uv run python -m compileall mewcode tests`，期望无编译错误）。
- [ ] 模块入口和 console script 均可启动；配置缺失时显示可读错误并返回 `1`，不显示堆栈（验证：分别运行 `env HOME="$(mktemp -d)" uv run python -m mewcode` 和 `env HOME="$(mktemp -d)" uv run mewcode`）。
- [ ] README 明确列出六个工具、单工具限制、确认策略、工作区边界、UTF-8 限制和非沙箱警告（验证：运行 `rg -n "read_file|write_file|edit_file|run_command|glob_files|search_code|sandbox|UTF-8|\.gitignore" README.md`）。
- [ ] 改动范围符合已批准文件清单且没有提交真实配置或 API key（验证：运行 `git status --short`、`git diff --check`，并检查 `.mewcode/config.yaml` 未被跟踪）。

## 端到端场景

- [ ] 场景 1：模型请求读取工作区文件，终端显示工具摘要但不显示完整内容；结果回灌后模型流式给出最终回答，Provider 总调用次数为二（验证：使用 fake OpenAI 流运行 CLI 集成测试，执行 `uv run pytest tests/test_tui.py -k e2e_read_file`）。
- [ ] 场景 2：模型请求新建文件，终端展示路径与 diff；输入 `yes` 后文件落盘，模型收到成功结果并给出最终回答（验证：运行 `uv run pytest tests/test_tui.py -k e2e_write_confirmed`）。
- [ ] 场景 3：模型请求修改或执行命令，用户输入非批准内容；文件和命令副作用均不存在，模型收到拒绝结果并解释未执行（验证：运行 `uv run pytest tests/test_tui.py -k e2e_rejected_action`）。
- [ ] 场景 4：模型请求访问工作区外符号链接，系统拒绝且外部文件保持不变，模型收到路径越界结果（验证：运行 `uv run pytest tests/test_tui.py -k e2e_workspace_escape`）。
- [ ] 场景 5：OpenAI 将一个工具参数拆成多个流事件，系统正确执行一次并回灌结果（验证：运行 `uv run pytest tests/test_runtime.py -k e2e_openai_tool_delta`）。
- [ ] 场景 6：Anthropic 将 `tool_use` 参数拆成多个增量，系统正确执行一次并保留协议内容块（验证：运行 `uv run pytest tests/test_runtime.py -k e2e_anthropic_tool_delta`）。
- [ ] 场景 7：模型首次请求两个工具，两个都不执行；最终回答说明本轮单工具限制（验证：运行 `uv run pytest tests/test_runtime.py -k e2e_multiple_tools`）。
- [ ] 场景 8：模型在结果回灌后再次请求工具，终端显示额度已用完且 Provider 调用次数保持二；下一轮普通聊天仍可继续（验证：运行 `uv run pytest tests/test_runtime.py -k e2e_tool_budget`）。
