# 结构化系统提示与缓存策略 Checklist

> 本清单在实现完成后逐项执行。只有实际运行或观察到证据后才能勾选；失败项必须保留实际结果，修复并重新验证后再更新。测试名称或文件位置调整时，检查项描述的外部行为与通过条件保持不变。

## 验收规则

- `[自动]`：使用确定性测试、编译或静态检查验证，不访问真实 Provider。
- `[人工]`：按固定输入观察实际工具、消息或界面行为，并把脱敏结果记录到 `manual-evaluation.md`。
- `[实网]`：允许使用真实 Provider 和有效凭据，但不得记录 API Key、认证头或完整原始响应。
- 自动化测试、人工硬性失败审计和实网缓存命中三类条件必须同时通过。
- 至少一个真实 Provider 的重复请求必须观察到 `cache-read > 0`；请求成功、缓存参数降级成功、字段缺失或值为零都不能替代该证据。
- 实网验证在自动化、安全和行为检查通过后执行；单个 Provider 最多一次预热加两次重复请求。

## 结构化提示行为

- [ ] C01 `[自动]` 七个固定模块的英文内容与 Plan 批准文本字节级一致，严格按 Identity → System Constraints → Task Mode → Action Execution → Tool Use → Tone and Style → Text Output 出现一次，模块间恰好一个空行；相同输入得到相同文本。（验证：运行 `uv run pytest tests/test_prompting.py -q -k 'catalog or stable_render'`，检查文案、顺序、分隔和重复构建断言）
- [ ] C02 `[自动]` 动态模块严格按 Active Mode → Environment → Custom Instructions → Activated Skills → Long-term Memory 排列，三个可选模块为空时连标题和分隔一起省略。（验证：运行 `uv run pytest tests/test_prompting.py -q -k 'optional or supplemental_render'`）
- [ ] C03 `[自动]` 分别改变环境、模式提醒、历史、iteration 和三个可选槽后，稳定提示及稳定前缀保持不变，变化只出现在动态请求区域。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_agent_run.py -q -k 'stable_render or cache_identity or iteration_prompt'`）
- [ ] C04 `[自动]` 调用方提供的自定义指令、Skill 和长期记忆各只出现一次；未提供内容时不读取项目文件、Skill 系统、记忆系统或外部数据。（验证：运行 `uv run pytest tests/test_prompting.py -q -k 'optional or environment'`，并用受控替身确认无文件遍历和网络调用）
- [ ] C05 `[自动]` 每轮补充消息只有一对 `<system-reminder>` 标签，包含 Plan 批准的静默处理声明及必需的模式和环境 Section，且不会被构造成用户消息。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_providers.py -q -k 'supplemental_render or prompt_mapping'`）
- [ ] C06 `[自动]` 任一动态字段包含保留标签片段时，构建在提交历史或调用 Provider 前失败；错误明确且不回显动态敏感内容。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_agent_session.py -q -k 'reminder_injection or prompt_failure'`）
- [ ] C07 `[自动]` execute、plan 和 do 的完整/精简文案与 Plan 批准文本一致，均在第 1、6、11……轮使用完整提醒，其余轮次使用更短的精简提醒；每个新运行从完整提醒重新开始。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_agent_run.py -q -k 'mode_text or run_prompt or iteration_prompt'`）
- [ ] C08 `[自动]` 每个运行只采集一次环境，且快照只含规范化工作目录、平台、Shell、日期和时区；不含 Git、目录列表、配置、密钥或其他环境变量。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_agent_session.py -q -k 'environment or prompt_snapshot'`）
- [ ] C09 `[自动]` 测试用额外 CACHEABLE 与 SUPPLEMENTAL Section 能按优先级进入各自通道，不需要修改两个 Provider 的排序逻辑；重复名称、重复优先级和跨通道错置会被拒绝。（验证：运行 `uv run pytest tests/test_prompting.py -q -k 'extra_section or invalid_builder'`）
- [ ] C10 `[自动]` 版本 `mewcode-prompt-v1`、稳定提示和规范化工具快照按批准 JSON 规则得到确定的 64 位 SHA-256；固定模块、额外缓存模块、工具顺序、描述或 Schema 变化会改变身份，动态内容变化不会改变身份。（验证：运行 `uv run pytest tests/test_prompting.py -q -k cache_identity`）
- [ ] C11 `[自动]` 运行开始后的工具名称、描述、Schema 和顺序来自防御性快照；修改调用方原始嵌套 Schema 不会改变已准备请求或缓存身份。（验证：运行 `uv run pytest tests/test_prompting.py -q -k 'tool_snapshot or cache_identity'`）
- [ ] C12 `[自动]` 非法模式、缺失固定模块、空或重复工具名等输入不会返回部分 Prompt；Prompting 的公开入口可独立导入，且构建过程不扫描仓库或访问网络。（验证：运行 `uv run pytest tests/test_prompting.py -q -k invalid_builder`、`uv run python -c 'from mewcode.prompting import PromptBuilder, RunPrompt, PromptOptions, capture_environment'`，并检查 Prompting 依赖边界）

## Agent 与统一请求集成

- [ ] C13 `[自动]` 有效输入依次完成命令解析、工具筛选、环境采集和 Prompt 构建，随后才提交用户历史；环境或 Prompt 构建失败时不新增历史、不调用 Provider 且不留下活动运行。（验证：运行 `uv run pytest tests/test_agent_session.py -q -k prompt_failure`）
- [ ] C14 `[自动]` 无效 `/plan`、`/do` 命令保持原有错误，并且不查询工具、不采集环境、不构建 Prompt、不调用 Provider、不提交历史。（验证：运行 `uv run pytest tests/test_agent_session.py -q -k invalid`）
- [ ] C15 `[自动]` 一个运行复用同一环境、稳定提示、工具快照和缓存身份，每次内部模型请求创建新的当轮提示包与统一请求。（验证：运行 `uv run pytest tests/test_agent_session.py tests/test_agent_run.py -q -k 'prompt_snapshot or iteration_prompt'`）
- [ ] C16 `[自动]` 系统补充消息只存在于当轮请求，不进入 Session 历史、assistant provider state、工具反馈历史或用户界面消息列表。（验证：运行 `uv run pytest tests/test_agent_run.py tests/test_providers.py tests/test_tui_app.py tests/test_tui_plain.py -q -k 'supplement_history or prompt_mapping or system_supplement'`）
- [ ] C17 `[自动]` 多轮工具循环的历史顺序保持 user → assistant/tool call → tool result，后续请求包含已提交反馈但不会重复持久化系统补充消息。（验证：运行 `uv run pytest tests/test_agent_run.py tests/test_providers.py -q -k 'supplement_history or provider_request_e2e'`）
- [ ] C18 `[自动]` 新运行从 iteration 1 开始；execute、plan 和 do 的公开行为及保存计划 ID 语义保持不变。（验证：运行 `uv run pytest tests/test_agent_session.py tests/test_agent_run.py -q -k 'iteration_prompt or plan or do'`）
- [ ] C19 `[自动]` plan 运行只获得只读工具，execute/do 获得完整工具；相同作用域的工具输入稳定，不同作用域形成不同且稳定的缓存身份。（验证：运行 `uv run pytest tests/test_agent_session.py tests/test_tool_registry.py tests/test_prompting.py -q -k 'tool_scope or definitions or cache_identity'`）
- [ ] C20 `[自动]` AgentRequest 不再携带自由文本 instructions；Collector 和所有测试 Provider 只接收统一、冻结的 ProviderRequest，取消令牌独立传递，Collector 不读取或修改 Prompt 内容。（验证：运行 `uv run pytest tests/test_agent_session.py -q -k agent_request` 和 `uv run pytest tests/test_agent_collector.py -q`）
- [ ] C21 `[自动]` 文本背压、流开始通知、工具调用聚合、缺失/重复 completed、completed 后事件、重复调用 ID 和取消行为均保持原有协议。（验证：运行 `uv run pytest tests/test_agent_collector.py tests/test_agent_run.py -q`）

## Provider 映射与缓存降级

- [ ] C22 `[自动]` OpenAI 请求把稳定提示仅放入 `instructions`，把 system supplement 作为 input 首项且位于历史之前；工具保持快照顺序，`prompt_cache_key` 等于缓存身份。（验证：运行 `uv run pytest tests/test_providers.py -q -k openai_prompt_mapping`）
- [ ] C23 `[自动]` 两个环境或用户输入不同但稳定前缀相同的 OpenAI 请求具有相同 instructions、工具和缓存键；稳定模块或工具变化时缓存输入随之变化。（验证：运行 `uv run pytest tests/test_providers.py tests/test_prompting.py -q -k 'openai_prompt_mapping or cache_identity'`）
- [ ] C24 `[自动]` OpenAI 五维 Usage 正确区分缺失、零和正数；显式布尔、负数、浮点或字符串值通过 Provider 错误通道失败。（验证：运行 `uv run pytest tests/test_providers.py -q -k openai_usage`）
- [ ] C25 `[自动]` OpenAI 只在流开始前收到明确关联 `prompt_cache_key` 的 HTTP 400/422 不支持错误时重试一次；第二次只删除缓存键，其余请求内容不变。（验证：运行 `uv run pytest tests/test_providers.py -q -k openai_cache_fallback_success`）
- [ ] C26 `[自动]` OpenAI 对认证、限流、模型、网络、普通 400/422 或收到任意事件后的错误不重试；错误文本经过密钥脱敏。（验证：运行 `uv run pytest tests/test_providers.py -q -k 'openai_cache_no_retry or openai_cache_redaction'`）
- [ ] C27 `[自动]` Anthropic 请求包含两个 system text block：稳定 block 带 ephemeral，动态 block 不带缓存标记；补充消息不进入 messages 历史。（验证：运行 `uv run pytest tests/test_providers.py -q -k anthropic_prompt_mapping`）
- [ ] C28 `[自动]` Anthropic 有工具时仅最后一个工具定义带 ephemeral，无工具时不生成伪造工具或空缓存块；工具顺序和 Schema 保持快照内容。（验证：运行 `uv run pytest tests/test_providers.py -q -k anthropic_prompt_mapping`）
- [ ] C29 `[自动]` 动态环境、模式或历史变化不改变 Anthropic 稳定 block 与工具前缀；固定提示或工具变化会形成不同稳定缓存输入。（验证：运行 `uv run pytest tests/test_providers.py tests/test_prompting.py -q -k 'anthropic_prompt_mapping or cache_identity'`）
- [ ] C30 `[自动]` Anthropic 正确归一化输入、输出、缓存读取和缓存创建量，total 保持不可用；后续事件缺失字段不覆盖已观测值，非法值通过 Provider 错误通道失败。（验证：运行 `uv run pytest tests/test_providers.py -q -k anthropic_usage`）
- [ ] C31 `[自动]` Anthropic 只在流开始前收到明确关联 `cache_control` 的 HTTP 400/422 不支持错误时重试一次；第二次只移除缓存标记，其余 JSON 不变。（验证：运行 `uv run pytest tests/test_providers.py -q -k anthropic_cache_fallback_success`）
- [ ] C32 `[自动]` Anthropic 对认证、限流、模型、网络、普通 400/422 或收到任意事件后的错误不重试；错误脱敏且原始嵌套 Schema 未被修改。（验证：运行 `uv run pytest tests/test_providers.py -q -k 'anthropic_cache_no_retry or anthropic_cache_redaction'`）
- [ ] C33 `[自动]` 两个 Provider 都不修改 ProviderRequest、PromptPackage 或工具 Schema；同一统一请求能产生等价的文本、工具调用、工具反馈和 Usage 事件。（验证：运行 `uv run pytest tests/test_providers.py -q -k provider_request_e2e`）
- [ ] C34 `[自动]` 缓存提示不受支持但满足批准降级条件，或成功响应完全缺失缓存字段时，请求仍正常完成；缓存指标保持不可用且界面不伪造字段。（验证：运行 `uv run pytest tests/test_providers.py tests/test_tui_presentation.py -q -k 'fallback_success or missing or none'`）
- [ ] C35 `[自动]` 显式非法缓存字段或损坏的 Provider 响应会停止当前运行，不提交该轮不完整历史、不发布或累计该轮 Usage，且不泄露凭据。（验证：运行 `uv run pytest tests/test_providers.py tests/test_agent_session.py tests/test_agent_run.py -q -k 'invalid_usage or provider_error or protocol'`）

## Usage、工具规则与界面

- [ ] C36 `[自动]` input、output、total、cache-read 和 cache-write 五个维度逐项累计；某维度任一轮为 `None` 后该累计维度保持 `None`，其他维度继续正确累计。（验证：运行 `uv run pytest tests/test_agent_run.py -q -k usage`）
- [ ] C37 `[自动]` 共享 Usage 文本保留原有 in/out/total 格式；缓存字段为 `None` 时省略、为零时显示、为正数时显示，current 和 cumulative 分别判断。（验证：运行 `uv run pytest tests/test_tui_presentation.py -q`）
- [ ] C38 `[自动]` 全屏与纯文本界面对同一 Usage 事件显示完全相同的共享文本，不新增缓存卡片或 Provider 分支；非 TTY/StringIO 路径保持可用。（验证：运行 `uv run pytest tests/test_tui_app.py tests/test_tui_plain.py tests/test_tui_presentation.py -q -k 'usage or shared_usage'`）
- [ ] C39 `[自动]` 六个工具描述与 Plan 批准文本字节级一致；全局 Tool Use 模块和相关描述同时表达专用工具优先及编辑前读取约定，每个工具只携带与自身相关的规则。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_tool_registry.py -q -k 'catalog or description'`）
- [ ] C40 `[自动]` 六个工具的名称、参数 Schema、权限、确认策略、执行策略和默认注册顺序未改变；描述变化会使缓存身份失效。（验证：运行 `uv run pytest tests/test_tool_registry.py tests/test_prompting.py -q -k 'description or register or cache_identity'`）
- [ ] C41 `[自动]` “专用工具优先”和“编辑前读取”仍只是提示层规则，没有新增运行时 read-before-write 拦截器，也没有改变工具自身安全检查。（验证：运行 `uv run pytest tests/test_file_tools.py tests/test_search_tools.py tests/test_command_tool.py tests/test_tool_registry.py -q`，并核对工具生产代码差异只改变批准的 description）
- [ ] C42 `[人工]` 界面中看不到 system supplement、缓存身份或内部模块内容；助手不会引用或专门回复 `<system-reminder>`。（验证：执行 S07、S08，并将实际输出观察记录到 `manual-evaluation.md`）

## 兼容性、安全与范围边界

- [ ] C43 `[自动]` 普通执行、`/plan` 和 `/do` 的成功路径、计划保存/完成状态及工具作用域全部通过现有回归测试。（验证：运行 `uv run pytest tests/test_agent_session.py tests/test_agent_run.py -q -k 'execute or plan or do'`）
- [ ] C44 `[自动]` 流式输出、工具反馈、确认、即时取消、早期迭代器关闭、错误恢复和事务性历史提交均无回归。（验证：运行 `uv run pytest tests/test_agent_control.py tests/test_agent_run.py tests/test_agent_session.py tests/test_providers.py tests/test_tui_app.py tests/test_tui_plain.py -q -k 'cancel or close or recovery or confirmation or history or stream'`）
- [ ] C45 `[自动]` 不新增用户必填配置；项目级与用户级配置查找顺序、模型选择、API Key 管理和 Anthropic thinking 行为保持不变。（验证：运行 `uv run pytest tests/test_config.py tests/test_cli.py tests/test_providers.py -q`）
- [ ] C46 `[自动/人工]` 稳定提示、环境、错误、Usage、自动化测试和人工记录中均不存在 API Key、认证头、完整环境变量集合或其他秘密。（验证：运行脱敏测试，审查新增差异与 `manual-evaluation.md`，搜索 `Authorization:`、`x-api-key:` 和 Bearer 值模式）
- [ ] C47 `[自动]` 未实现 AGENTS/项目指令加载、Skill 发现与激活、长期记忆检索或持久化、真实 MCP、自动评分、本地响应缓存、其他 Provider 或对话历史持久化。（验证：检查新增公共入口、配置项、依赖和变更文件，确认只有批准的调用方文本插槽）
- [ ] C48 `[自动]` 消息模型、配置、Scheduler、SSE 解析和工具执行边界未被改造；Prompting 不反向依赖 Agent 或具体 Provider，Provider 不自行维护模块内容顺序。（验证：检查依赖图与变更清单，运行 `rg -n 'mewcode\.agent|mewcode\.providers\.(openai|anthropic)' mewcode/prompting` 期望无匹配）
- [ ] C49 `[人工]` `manual-evaluation.md` 包含同一模型下的基线与候选元数据、九个固定场景的输入/观察/结果、比较等级、缓存表和最终结论；失败或未覆盖项未被美化，定性比较未宣称统计显著性。（验证：逐项复核记录表完整性和结论措辞）
- [ ] C50 `[人工]` 候选版本不存在五类硬性失败：Shell 替代适用专用工具、修改已有文件前未读、回复系统标签、规划模式越权、输出秘密。（验证：审计 S01–S08 的实际工具序列和输出；任一命中即保持未通过）
- [ ] C51 `[实网]` 至少一个支持 Prompt Caching 且稳定前缀达到最小缓存长度的真实 Provider 在重复请求中返回 `cache-read > 0`；动态标签未泄露，OpenAI 不伪造写入量，Anthropic 返回创建量时正确展示。（验证：执行 S09；首选 Provider 最多三次仍未命中时停止对其计费并按同一上限尝试备用 Provider，记录脱敏后的模型、稳定输入长度和 Usage；两家都没有正数则保持未通过）

## 工程验证

- [ ] C52 `[自动]` Prompting、Agent、双 Provider、工具、Usage 和双界面的聚焦测试全部通过，且测试 HTTP/SSE 响应均来自本地可控替身。（验证：运行 `uv run pytest tests/test_prompting.py tests/test_agent_collector.py tests/test_agent_events.py tests/test_agent_run.py tests/test_agent_session.py tests/test_cli.py tests/test_providers.py tests/test_tool_registry.py tests/test_tui_presentation.py tests/test_tui_app.py tests/test_tui_plain.py -q`）
- [ ] C53 `[自动]` 完整测试套件零失败，不通过跳过测试、放宽断言或访问真实网络取得绿色结果。（验证：运行 `uv run pytest` 并记录实际通过数量与 snapshot 数量）
- [ ] C54 `[自动]` 全部生产和测试模块可编译，Prompting 与 ProviderRequest 公共入口可从干净 Python 进程导入。（验证：运行 `uv run python -m compileall mewcode tests` 和 `uv run python -c 'import mewcode.cli; from mewcode.prompting import PromptBuilder; from mewcode.providers import ProviderRequest'`）
- [ ] C55 `[自动]` 依赖锁有效且所有已跟踪变更无空白错误。（验证：运行 `uv lock --check` 和 `git diff --check`）
- [ ] C56 `[自动]` 从无配置的临时 HOME 与空工作目录启动模块入口和控制台脚本，二者均退出码 1、只显示配置缺失错误，不出现 traceback、系统提示或缓存身份。（验证：按 task.md T113 的两个临时环境命令执行并记录 stdout/stderr）
- [ ] C57 `[自动/人工]` 四份里程碑文档对模块名称、顺序、“模型请求轮次”、cache-read/cache-write 和硬性通过条件保持一致；`docs/HARNESS_ARCHITECTURE.md` 未修改或暂存，临时评估工作区及凭据未进入仓库。（验证：交叉审阅 `spec.md`、`plan.md`、`task.md`、`checklist.md`，检查 `git status --short` 与最终提交文件清单）

## 端到端场景

- [ ] S01 `[人工]` 专用搜索：在固定非敏感工作区提交“查找并解释一段代码”的输入；实际调用优先使用 search_code、glob_files、read_file，不以 run_command 代替，并给出基于观察的解释。（验证：记录基线/候选工具序列、回答和比较等级）
- [ ] S02 `[人工]` 局部编辑：请求修改已有文件的一处文本；同一路径 read_file 先于 edit_file，old_text 来自新鲜读取，修改后执行适当验证。（验证：记录相对路径、完整调用顺序、确认过程和结果）
- [ ] S03 `[人工]` 完整替换：请求完整替换已有文件；同一路径 read_file 先于 write_file，未使用 Shell 直接写入，确认后结果与请求一致。（验证：记录调用顺序、确认和文件结果）
- [ ] S04 `[人工]` 创建新文件：请求创建明确不存在的文件；直接使用 write_file，不进行无意义的失败读取，文件不被加入产品仓库。（验证：记录初始不存在证据、工具序列和创建结果）
- [ ] S05 `[人工]` 聚焦测试：请求运行一个安全的项目测试；在没有专用测试工具时合理使用 run_command，经过用户确认，并准确报告实际退出结果。（验证：记录命令类别、确认、退出结果和回答）
- [ ] S06 `[人工]` 规划模式：用固定 `/plan` 输入分析复杂任务；只使用只读工具，不修改状态，最终计划基于观察到的代码和依赖且可直接实施。（验证：记录工具作用域、工作区前后状态和计划质量）
- [ ] S07 `[人工]` 六轮循环：运行需要至少六次内部模型请求的固定任务；第 1、6 轮使用完整提醒，中间轮次精简，模型持续遵守模式且不复述 system-reminder；未达到六轮则标记未覆盖。（验证：记录实际 iteration、模式行为和可见输出）
- [ ] S08 `[人工]` 普通问答与总结：提交固定解释/总结请求；回答结论先行、清晰区分已验证事实与建议，不暴露提示模块、环境注入、缓存身份或系统标签。（验证：按固定观察项记录基线/候选结果）
- [ ] S09 `[实网]` 重复稳定前缀：确认模型支持缓存且稳定输入达到最小长度，使用同一 Provider、模型、稳定提示和工具顺序，依次发送一次预热及最多两次不同普通问题；首选未命中时停止对其计费并按相同上限尝试另一 Provider，至少一个重复请求必须显示 `cache-read > 0`。（验证：记录两家 Provider 的脱敏 Usage 表或备用免执行理由、动态标签泄露检查和最终命中/未通过结论）

## AC 覆盖索引

| Spec 验收标准 | Checklist 证据 |
|---|---|
| AC1 | C01 |
| AC2 | C02 |
| AC3 | C03、C10、C15 |
| AC4 | C02、C04 |
| AC5 | C05、C22–C23、S09 |
| AC6 | C05、C27–C29、S09 |
| AC7 | C05、C16、C42 |
| AC8 | C07、C18、S07 |
| AC9 | C08、C46 |
| AC10 | C39、S01–S04 |
| AC11 | C10–C11、C19、C40 |
| AC12 | C24、C36–C38 |
| AC13 | C30、C36–C38 |
| AC14 | C36 |
| AC15 | C37–C38 |
| AC16 | C22–C35、C52 |
| AC17 | C51、S09 |
| AC18 | C49–C50、S01–S09 |
| AC19 | C21、C43–C45、C53 |
| AC20 | C25、C31、C34、C37–C38 |
| AC21 | C06、C24、C26、C30、C32、C35、C46 |
| AC22 | C04、C07–C08、C12、C47 |
| AC23 | C09 |
| AC24 | C57 |
