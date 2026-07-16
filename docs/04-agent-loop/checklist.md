# MewCode Agent Loop Checklist

> 实现完成后逐项运行验证并记录实际证据。只有观察到预期行为才能将 `[ ]` 改为 `[x]`；测试名称或文件位置调整时，保留条目描述的外部行为不变。

## 验收实录（2026-07-16）

- C01–C24、C26、C29–C34：Agent 核心与会话验收通过，`76 passed`；其中 Plan Mode 点名隐藏写工具已实测回写 `unknown_tool` 且零执行，立即取消与消费者提前退出均释放 Session，计划/执行在取消、Provider 错误、未知工具与 10 轮上限后均按规格保留或可重试。
- C25、C27、C28、C35、C44：Provider/工具/工作区回归 `79 passed`，TUI/CLI/配置回归 `78 passed`；4 张 Textual 快照通过，配置与依赖文件无功能差异。
- C36–C38：异步界面与遗留入口扫描通过；`ChatRuntime|TurnCancellation|TurnPhaseChanged|ToolInteraction|TuiEventBridge|call_from_thread|thread=True` 无匹配。
- C39：清单指定的 Agent、Provider、工具和 TUI 聚焦集 `130 passed`，4 张快照通过。
- C40：`uv run pytest` 实际结果 `233 passed`，4 张快照通过。
- C41：`uv run python -m compileall mewcode tests` 返回 0，无编译错误。
- C42：`uv lock --check` 返回 0；`pyproject.toml`、`uv.lock` 无本里程碑功能差异。
- C43：从空临时 cwd 与空 HOME 启动模块入口和 console script，二者均只显示缺失配置错误、实际退出码 1、无堆栈。
- C45：README 关键字与人工核对通过，覆盖 Agent Loop、五类停止、`/plan`、`/do`、逐次确认及权限/压缩/持久化边界。
- C46：`git diff --check c73872d`、真实配置跟踪检查、API key 新增行扫描、批准文件清单人工核对与最终工作树 clean 复查均通过。
- E01–E08：脚本化端到端集合实际 `15 passed`，覆盖完整四工具自主链、混合批次屏障及全屏卡片身份、Plan/Do、四种取消时点、断流恢复、三类消费者等价、双 Provider 与进程重启边界。


## 自主循环与停止条件

- [x] C01 [AC1] 普通请求在模型依次提出至少三轮不同工具调用时，无需用户补发“继续”即可逐轮执行、回写观察并最终输出无工具调用的回答（验证：`uv run pytest tests/test_agent_run.py -k react_loop`，期望 Provider 调用、工具反馈和最终回答顺序断言全部通过）。
- [x] C02 [AC6] 首轮或任意后续轮出现完整无工具回答时，只提交一次助手消息并以自然完成结束，此后不再请求模型（验证：`uv run pytest tests/test_agent_run.py -k "natural_completion or assistant_commit"`）。
- [x] C03 [AC7] 连续 10 轮均请求工具时，第 10 轮完整批次结束后以迭代上限停止，Provider 调用数恰为 10，且没有第 11 轮或额外总结请求（验证：`uv run pytest tests/test_agent_run.py -k iteration_limit`）。
- [x] C04 [AC11] 连续三轮只有未知工具时，前两轮收到结构化错误，第三轮提交反馈后停止；插入已知工具会重置连续计数（验证：`uv run pytest tests/test_agent_run.py -k unknown_tool_limit`）。

## 流式收集、事件与 Token

- [x] C05 [AC2] 慢速模型流结束前文本持续可见，完整结束后文本和所有工具参数与片段一致；提前断流时调用不执行且残缺助手消息不进历史（验证：`uv run pytest tests/test_agent_collector.py -k "text or tool_call or provider_error"`）。
- [x] C06 [AC3] 一次包含模型、工具、确认和终止的运行只通过一条 Agent 异步事件流观察；替换为测试、纯文本或全屏消费者不会改变 Provider/工具调用序列（验证：`uv run pytest tests/test_agent_events.py tests/test_tui_plain.py tests/test_tui_app.py -k "event or events or normal_turn"`）。
- [x] C07 [AC4] 每轮事件包含运行模式、`当前轮次/10`，并按真实行为经过等待模型、接收响应、执行工具、等待确认、回写结果和结束阶段（验证：`uv run pytest tests/test_agent_run.py tests/test_tui_plain.py tests/test_tui_app.py -k progress`）。
- [x] C08 [AC5] 三轮 Provider 用量逐轮原样报告，已知累计值等于各轮之和；任一缺失维度显示不可用并使该累计维度保持不可用（验证：`uv run pytest tests/test_providers.py tests/test_agent_run.py -k usage`）。
- [x] C09 [AC22] 模型流、并发工具和确认等待期间界面仍可刷新、保留草稿并处理取消；快速片段遇到慢消费者时不丢失、不乱序，队列容量受限（验证：`uv run pytest tests/test_agent_control.py tests/test_tui_app.py -k "backpressure or rapid_chunks or confirmation"`）。
- [x] C10 [AC23] 每次运行有唯一开始和唯一终止事件，序号严格递增；终止后迟到事件被忽略，运行、轮次、批次和调用身份可稳定关联，停止原因可机器判定（验证：`uv run pytest tests/test_agent_events.py tests/test_agent_control.py -k "sequence or terminal or late_event or identity"`）。

## 取消、错误恢复与历史一致性

- [x] C11 [AC8] 在首片段前和部分文本后取消都会关闭活动流、停止新片段并以用户取消结束；已显示部分文本不进入历史（验证：`uv run pytest tests/test_agent_run.py -k "cancel_model or cancel_partial_text"`）。
- [x] C12 [AC9] 在并发读工具、串行副作用工具和确认等待中取消时，未开始工作不启动、可取消任务结束、后续模型不请求且没有遗留任务；已开始副作用不显示为已回滚（验证：`uv run pytest tests/test_agent_run.py tests/test_command_tool.py tests/test_file_tools.py -k cancellation`）。
- [x] C13 [AC10] 连接、SSE 解析、重复完成和缺少完成四类流错误都立即以 Provider 错误结束，不执行残缺调用、不自动重试，并允许下一请求成功（验证：`uv run pytest tests/test_sse.py tests/test_agent_collector.py tests/test_agent_run.py -k "error or completed or recovery"`）。
- [x] C14 [AC21] OpenAI 与 Anthropic 均能重放多轮助手调用和多个工具结果；取消、流错误或未完成批次不会留下孤立调用、重复结果或 Provider 无法接收的历史（验证：`uv run pytest tests/test_providers.py tests/test_agent_run.py -k "history or iteration_transaction or transaction_on_cancel"`）。
- [x] C15 [AC25] 单个工具失败会作为反馈让模型在剩余轮次调整；模型流错误只结束当前运行，两种情况后普通请求或计划操作均可成功（验证：`uv run pytest tests/test_agent_run.py tests/test_agent_session.py tests/test_tui_app.py -k recovery`）。

## 多工具调度与确认

- [x] C16 [AC12] 同一响应混合多个有效调用、一个参数错误和一个未知工具时，有效调用全部执行，两个无效调用各自收到结构化错误，调用 ID 与结果不串位（验证：`uv run pytest tests/test_agent_scheduler.py -k "parse or invalid or unknown"`）。
- [x] C17 [AC13] `read_file`、`glob_files`、`search_code` 被标记为可并发，`write_file`、`edit_file`、`run_command` 被标记为串行，未声明策略的测试工具按串行处理（验证：`uv run pytest tests/test_tool_registry.py -k "builtin_policy or default_policy"`）。
- [x] C18 [AC14] “读 A、读 B、写 C、读 D”中 A/B 确实重叠，C 等待 A/B 全部结束，D 等待 C 结束，任何串行工具都不与其他调用重叠（验证：`uv run pytest tests/test_agent_scheduler.py -k "parallel or barrier or serial"`）。
- [x] C19 [AC15] 并发工具可按实际完成顺序实时报告，但回写模型的反馈仍按原调用顺序；成功、错误、拒绝、超时、无效参数和未知工具结构一致（验证：`uv run pytest tests/test_agent_scheduler.py tests/test_tool_executor.py -k "completion_order or error or rejected or timeout"`）。
- [x] C20 [AC16] 同一响应中的多个副作用工具逐个确认；批准后才执行，拒绝后无副作用，批准和拒绝结果均回写模型且循环继续（验证：`uv run pytest tests/test_agent_scheduler.py tests/test_tui_plain.py tests/test_tui_app.py -k confirmation`）。

## Plan Mode

- [x] C21 [AC17] `/plan <任务>` 可连续使用读取、查找和搜索形成计划；模型看不到写入、修改或命令定义，点名调用未开放工具时收到未知工具反馈，最终计划成功保存（验证：`uv run pytest tests/test_agent_session.py -k "plan_save or read_only"`）。
- [x] C22 [AC18] 已有计划 A 时成功规划会替换为 B；取消、流错误、迭代上限或连续未知工具停止均保留 A（验证：`uv run pytest tests/test_agent_session.py -k "plan_replace or plan_preserve"`）。
- [x] C23 [AC19] READY 计划存在时 `/do` 使用计划正文和全部工具；无计划、已完成计划或 `/do` 带额外正文时直接返回明确无效请求，Provider 和工具调用数均为零（验证：`uv run pytest tests/test_agent_session.py -k "command_parser or do_lifecycle"`）。
- [x] C24 [AC20] `/do` 自然完成后不可重复执行；取消、流错误、未知工具或迭代上限后同一计划可重试，期间普通请求不改变计划状态（验证：`uv run pytest tests/test_agent_session.py -k do_lifecycle`）。

## 安全、可测试性与兼容性

- [x] C25 [AC24] 参数、预览、结果、错误、进度和界面事件均不含测试 API key；大读取/搜索结果不会完整进入展示事件，工作区逃逸、超时、截断和副作用确认仍生效（验证：`uv run pytest tests/test_agent_events.py tests/test_tool_executor.py tests/test_workspace.py tests/test_tui_widgets.py tests/test_providers.py -k "safe or redaction or escape or timeout or truncation"`）。
- [x] C26 [AC26] 循环、并发、停止、Token、确认和计划生命周期测试只使用替代 Provider/工具、注入时钟与 Event/Barrier，不需要真实网络、危险命令或基于真实 sleep 的同步（验证：运行 `uv run pytest tests/test_agent_control.py tests/test_agent_scheduler.py tests/test_agent_run.py tests/test_agent_session.py`，期望稳定通过且无外部服务要求）。
- [x] C27 [AC27] 六个既有工具、普通无工具聊天、配置优先级、双 Provider、全屏/纯文本、`exit`、`quit` 和中断行为全部回归通过（验证：`uv run pytest tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py tests/test_config.py tests/test_providers.py tests/test_tui_app.py tests/test_tui_plain.py tests/test_cli.py`）。
- [x] C28 [AC28] 关闭并新建 Session 或重启 CLI 后不恢复计划、Agent 进度或用量；无需新增配置字段即可启动，项目级配置仍优先于用户级配置（验证：`uv run pytest tests/test_agent_session.py tests/test_config.py tests/test_cli.py -k "close or priority or startup"`，并比较 `pyproject.toml`、`uv.lock`、`config.yaml.example` 无功能差异）。

## 架构与集成

- [x] C29 `AgentSession.start()` 返回单次 `AgentRun`；界面只消费公共事件并通过 Run 取消/确认，不读取 Collector、Scheduler 或内部通道状态（验证：`uv run pytest tests/test_agent_events.py tests/test_agent_session.py -k public_api`）。
- [x] C30 依赖方向保持无环：Provider 和工具不导入 Agent/TUI/CLI，工具执行器不依赖界面，TUI 不直接依赖具体 Provider 或工具实现（验证：`uv run pytest tests/test_agent_events.py tests/test_agent_session.py -k import_direction`）。
- [x] C31 Agent 测试仅依赖统一 Provider 事件；OpenAI 的 instructions 和 Anthropic 的 system 均在每轮请求中保持模式指令，原生协议状态不泄漏到 Agent 事件（验证：`uv run pytest tests/test_providers.py tests/test_agent_run.py -k "instructions or system or provider_state"`）。
- [x] C32 事件通道只允许一个消费者；消费者提前退出会取消运行并清理确认，终止后没有后台任务或未处理异常（验证：`uv run pytest tests/test_agent_control.py -k "single_consumer or consumer_close or cleanup"`）。
- [x] C33 `AgentSession.close()` 幂等取消活动 Run 并只关闭一次其拥有的 Provider；Provider 只关闭自己创建的 HTTP 客户端，不关闭注入客户端（验证：`uv run pytest tests/test_agent_session.py tests/test_providers.py -k "close or client_ownership"`）。
- [x] C34 同一 Session 同时最多一个普通请求、`/plan` 或 `/do`；活动运行结束后可继续下一请求且完整历史仍可回放（验证：`uv run pytest tests/test_agent_session.py -k "single_run or history"`）。
- [x] C35 写文件取消只能留下旧文件或完整新文件；命令超时/取消会终止进程组，不留下继续运行的子进程（验证：`uv run pytest tests/test_file_tools.py tests/test_command_tool.py -k "atomic or cancellation or process_group"`）。
- [x] C36 全屏模式使用异步 Textual Worker，纯文本模式使用异步运行循环；仓库中不存在 Agent 专用线程桥、`thread=True` 或 `call_from_thread` 路径（验证：`uv run pytest tests/test_tui_app.py tests/test_tui_plain.py -k "async_worker or events"`，并运行 `! rg -n "TuiEventBridge|call_from_thread|thread=True" mewcode`）。
- [x] C37 完整工具结果只进入模型反馈，界面只接收安全摘要、状态、耗时、错误和截断信息（验证：`uv run pytest tests/test_agent_events.py tests/test_tui_widgets.py tests/test_tui_app.py -k "safe or hidden_result"`）。
- [x] C38 旧 `ChatRuntime`、TurnEvent 和 `ToolInteraction` 入口已移除且无兼容转发，所有真实调用方均使用新 Agent 公共入口（验证：`! rg -n "ChatRuntime|TurnCancellation|TurnPhaseChanged|ToolInteraction|TuiEventBridge" mewcode tests`）。

## 编译、测试与交付

- [x] C39 Agent、Provider、工具和 TUI 聚焦测试全部通过（验证：`uv run pytest tests/test_agent_events.py tests/test_agent_control.py tests/test_agent_collector.py tests/test_agent_scheduler.py tests/test_agent_run.py tests/test_agent_session.py tests/test_providers.py tests/test_tool_executor.py tests/test_tui_app.py tests/test_tui_plain.py`）。
- [x] C40 全部单元、集成和快照测试通过（验证：`uv run pytest`，期望零失败、零错误）。
- [x] C41 项目与测试语法编译通过（验证：`uv run python -m compileall mewcode tests`，期望返回 0 且无编译错误）。
- [x] C42 锁文件仍与项目声明一致且没有新增生产或测试依赖（验证：`uv lock --check`，并运行 `git diff -- pyproject.toml uv.lock`，期望无功能改动）。
- [x] C43 模块入口和 console script 均可启动；空 HOME 下配置缺失时只显示可读错误、返回 1 且无堆栈（验证：分别运行 `env HOME="$(mktemp -d)" uv run python -m mewcode` 和 `env HOME="$(mktemp -d)" uv run mewcode`）。
- [x] C44 配置文件位置、项目级优先级、Provider 字段与示例配置保持不变（验证：`uv run pytest tests/test_config.py tests/test_cli.py`，并检查 `git diff -- config.yaml.example mewcode/config.py` 无功能改动）。
- [x] C45 README 明确说明 Agent Loop、五类停止条件、`/plan`、`/do`、逐次确认及本阶段不包含的权限/压缩/持久化边界（验证：`rg -n "Agent Loop|/plan|/do|iteration|unknown|cancel|confirm|permission|context|persist" README.md`）。
- [x] C46 改动范围符合批准的文件清单，无尾随空白、真实配置、API key 或无关文件（验证：运行 `git status --short`、`git diff --check`、`test -z "$(git ls-files -- .mewcode/config.yaml)"` 和 `! git diff -U0 | rg '^\+.*sk-(ant-)?[A-Za-z0-9_-]{20,}'`，期望均通过并人工核对文件清单）。

## 端到端场景

- [x] E01 普通任务依次触发“读取 → 搜索 → 修改并确认 → 运行验证并确认 → 最终回答”，用户不发送中间提示，模型依据每次结果自动调整并自然结束（验证：使用脚本化 Provider 和临时工作区运行 `uv run pytest tests/test_agent_run.py tests/test_tui_plain.py -k e2e_autonomous_task`）。
- [x] E02 单个响应按“读 A、读 B、写 C、读 D”调用：A/B 并发，C 单独确认并形成屏障，D 最后执行；界面完成事件可乱序而模型反馈保持 A/B/C/D（验证：`uv run pytest tests/test_agent_scheduler.py tests/test_tui_app.py -k e2e_mixed_batch`）。
- [x] E03 输入 `/plan 分析并修改项目` 时只执行三种读工具并保存计划；随后 `/do` 恢复全工具、逐次确认副作用、自然完成后拒绝第二次 `/do`（验证：`uv run pytest tests/test_agent_session.py tests/test_tui_plain.py -k e2e_plan_do`）。
- [x] E04 在部分模型文本、并发读工具、写入确认和活动命令四个时点分别取消，终端恢复可输入状态，当前残缺事务不进历史且下一请求成功（验证：`uv run pytest tests/test_agent_run.py tests/test_tui_app.py -k e2e_cancel_recovery`）。
- [x] E05 Provider 在部分文本后断流时保留已显示文本但不执行已收集工具；运行显示 Provider 错误，同一会话下一次普通请求成功（验证：`uv run pytest tests/test_agent_run.py tests/test_tui_plain.py -k e2e_stream_error_recovery`）。
- [x] E06 同一脚本化运行分别由测试消费者、纯文本界面和全屏界面消费时，Provider 请求、工具执行、反馈历史和最终停止原因一致（验证：`uv run pytest tests/test_tui_plain.py tests/test_tui_app.py -k e2e_consumer_equivalence`）。
- [x] E07 OpenAI Responses 与 Anthropic Messages 分别完成多轮、多工具、usage、取消和历史回放场景，缺失用量字段明确显示不可用（验证：`uv run pytest tests/test_providers.py tests/test_agent_run.py -k e2e_dual_provider`）。
- [x] E08 退出并重新启动后 `/do` 明确提示无计划，配置仍按项目级优先；普通聊天、`exit` 和 `quit` 保持可用（验证：`uv run pytest tests/test_cli.py tests/test_tui_plain.py tests/test_config.py -k e2e_restart`）。
