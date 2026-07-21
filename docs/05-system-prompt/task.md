# 结构化系统提示与缓存策略 Tasks

> 本文基于已批准的 `spec.md` 与 `plan.md`。只有 `checklist.md` 也获得批准后，才按此列表开始实现。

## 文件清单

### 新建

| 文件 | 职责 |
|---|---|
| `mewcode/prompting/__init__.py` | Prompting 深模块公开入口 |
| `mewcode/prompting/types.py` | Prompt、环境和通道数据类型 |
| `mewcode/prompting/sections.py` | 固定模块及三种模式的完整/精简文案 |
| `mewcode/prompting/environment.py` | 最小环境快照采集 |
| `mewcode/prompting/builder.py` | 渲染、校验、工具快照、缓存身份和轮次补充 |
| `mewcode/providers/cache.py` | 严格的缓存提示不支持错误分类 |
| `tests/test_prompting.py` | Prompting 单元和确定性测试 |
| `tests/test_tui_presentation.py` | Usage 共享格式化测试 |
| `docs/05-system-prompt/manual-evaluation.md` | 实网缓存验证与人工对比记录 |

### 修改

| 文件 | 职责 |
|---|---|
| `mewcode/providers/base.py` | `ProviderRequest`、五维 `TokenUsage` 和 Provider 协议 |
| `mewcode/providers/__init__.py` | 新公共类型导出 |
| `mewcode/providers/openai.py` | OpenAI 请求映射、Usage 和缓存降级 |
| `mewcode/providers/anthropic.py` | Anthropic 请求映射、Usage 和缓存降级 |
| `mewcode/agent/types.py` | 删除 `AgentRequest.instructions` |
| `mewcode/agent/session.py` | 运行级 Prompt 准备和安全提交顺序 |
| `mewcode/agent/run.py` | 每轮 `PromptPackage`、统一请求和五维累计 |
| `mewcode/agent/collector.py` | 收敛为 `ProviderRequest` 输入 |
| `mewcode/cli.py` | 组合默认 Prompt Builder 与固定 workspace 环境工厂 |
| `mewcode/tools/file_tools.py` | 三个文件工具描述 |
| `mewcode/tools/search_tools.py` | 两个搜索工具描述 |
| `mewcode/tools/command.py` | Shell 工具描述 |
| `mewcode/tui/presentation.py` | 可选缓存指标格式化 |
| `tests/test_agent_collector.py` | Collector 统一请求测试 |
| `tests/test_agent_events.py` | 五维 Usage 事件契约 |
| `tests/test_agent_run.py` | RunPrompt、每轮请求和累计测试 |
| `tests/test_agent_session.py` | Prompt 准备、历史提交、模式和环境测试 |
| `tests/test_cli.py` | 组合根测试 |
| `tests/test_providers.py` | 双 Provider 请求、Usage、降级和 E2E 测试 |
| `tests/test_tool_registry.py` | 六个工具描述及稳定性测试 |
| `tests/test_tui_app.py` | 全屏测试 Provider 迁移及缓存 Usage |
| `tests/test_tui_plain.py` | 纯文本测试 Provider 迁移及缓存 Usage |

### 明确不改

- `docs/HARNESS_ARCHITECTURE.md`
- `mewcode/messages.py`
- `mewcode/config.py`
- `mewcode/agent/scheduler.py`
- `mewcode/providers/sse.py`
- 工具执行、确认、Workspace 和持久历史边界

## 执行约束

- 每个任务验证通过后才能进入依赖它的任务。
- 提交时只暂存任务明确列出的文件，始终排除用户已有的 `docs/HARNESS_ARCHITECTURE.md`。
- 不提交 API Key、认证头、真实敏感响应或临时评估工作区。
- 自动化测试不得访问真实 Provider；实网请求只在明确标记的人工任务中发生。
- 不推送远端；本任务列表只要求本地逻辑提交。

## 阶段 A：建立人工对比基线

### T1：创建人工评估文档骨架

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** 无

**步骤：**

1. 写入实网缓存验证前置条件、最多三次请求的成本边界和脱敏要求。
2. 写入九个已批准的固定场景输入、观察项和基线/候选记录表。
3. 写入硬性失败定义及最终结论区。

**验证：** `rg -n '实网缓存|专用工具|编辑前读取|规划模式|六轮|输出风格|硬性失败' docs/05-system-prompt/manual-evaluation.md`，期望各栏目均存在。

### T2：记录基线元数据

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T1

**步骤：**

1. 记录当前基线提交、Provider、模型和执行日期。
2. 只记录配置名称，不复制 API Key、认证头或完整配置。
3. 注明当前工作树只有里程碑文档和用户原有未跟踪文件。

**验证：** 检查基线元数据行均非空，并运行 `rg -n 'api[_-]?key|Authorization|x-api-key' docs/05-system-prompt/manual-evaluation.md`，期望没有真实凭据值。

### T3：运行基线“专用搜索工具”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T2

**步骤：**

1. 在非敏感临时工作区提交固定的代码查找与解释请求。
2. 记录实际使用的工具顺序，特别标出是否以 `run_command` 代替搜索工具。
3. 记录最终回答的可用性，不修改评估标准。

**验证：** 对应基线行包含固定输入、实际工具序列和观察结论。

### T4：运行基线“局部编辑前读取”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T3

**步骤：**

1. 在临时工作区准备一个可安全修改的 UTF-8 文件。
2. 提交固定的单处文本替换请求并记录工具调用顺序。
3. 明确记录同一路径的 `read_file` 是否先于 `edit_file`。

**验证：** 对应基线行包含目标相对路径、调用顺序和“先读/未先读”结论，不包含文件敏感内容。

### T5：运行基线“完整替换已有文件”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T4

**步骤：**

1. 使用临时工作区中的非敏感完整替换样例。
2. 记录 `read_file` 与 `write_file` 的先后关系。
3. 记录是否错误使用 Shell 直接写文件。

**验证：** 对应基线行包含调用顺序、专用工具判断和结果。

### T6：运行基线“创建新文件”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T5

**步骤：**

1. 选择一个明确不存在的临时相对路径。
2. 提交固定创建请求。
3. 记录是否直接使用 `write_file`，以及是否发生无意义的失败读取。

**验证：** 对应基线行记录新路径、实际调用和结论；临时文件不加入仓库。

### T7：运行基线“聚焦测试命令”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T6

**步骤：**

1. 提交固定的安全测试命令请求。
2. 记录是否合理选择 `run_command`。
3. 记录是否出现用户确认以及命令实际结果。

**验证：** 对应基线行包含命令类别、确认行为和实际结果，不记录环境凭据。

### T8：运行基线“规划模式只读”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T7

**步骤：**

1. 使用固定 `/plan` 输入启动复杂任务分析。
2. 记录工具访问范围和是否发生任何修改。
3. 记录计划是否基于观察到的代码与依赖。

**验证：** 对应基线行明确写出“只读/发生修改”和计划可执行性。

### T9：运行基线“至少六轮工具循环”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T8

**步骤：**

1. 使用固定、非敏感且需要连续观察的任务，尝试产生至少六次内部模型请求。
2. 记录实际 iteration 数和模式遵守变化。
3. 若未达到六轮，按实际结果标记“未覆盖”，不得伪造观察。

**验证：** 对应基线行包含实际 iteration 数、是否达到六轮及模式保持情况。

### T10：运行基线“输出风格”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T9

**步骤：**

1. 提交固定的解释与总结请求。
2. 记录是否先给结论、是否清晰区分已验证与建议。
3. 记录是否暴露内部提示、缓存身份或系统标签。

**验证：** 对应基线行包含固定观察项的逐项结论。

### T11：记录基线缓存可观测性

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T10

**步骤：**

1. 连续运行两次等价稳定前缀请求。
2. 记录当前 Usage 是否能观察缓存读取或写入量。
3. 不因当前无缓存字段而宣称命中或未命中。

**验证：** 基线缓存行明确区分“不可观测”“零”和“正数”。

### T12：审计基线记录

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T3–T11

**步骤：**

1. 确认所有基线场景都有输入、观察和结论。
2. 删除 API Key、认证头、绝对敏感路径及完整原始响应。
3. 保留失败和未覆盖项，不美化结果。

**验证：** 人工逐行复核后运行 `git diff --check -- docs/05-system-prompt/manual-evaluation.md`，期望无格式问题。

### T13：提交批准文档与基线记录

**文件：** `docs/05-system-prompt/{spec,plan,task,checklist,manual-evaluation}.md`
**依赖：** T12

**步骤：**

1. 只暂存本里程碑五份文档。
2. 创建一个文档与基线逻辑提交。
3. 确认 `docs/HARNESS_ARCHITECTURE.md` 未被暂存。

**验证：** `git show --stat --oneline -1` 只显示里程碑文档；`git status --short` 仍保留用户原有文件且没有意外代码改动。

## 阶段 B：实现 Prompting 深模块

### T14：建立 Prompting 类型文件

**文件：** `mewcode/prompting/types.py`
**依赖：** T13

**步骤：**

1. 定义 `PromptChannel`。
2. 定义冻结的 `PromptSection`。
3. 加入所需的标准库和共享类型导入，不导入 Agent 或具体 Provider。

**验证：** `uv run python -m compileall mewcode/prompting/types.py` 通过。

### T15：实现 PromptSection 自校验

**文件：** `mewcode/prompting/types.py`
**依赖：** T14

**步骤：**

1. 对名称和内容做首尾空白规范化。
2. 拒绝空名称、空内容和非法 Priority。
3. 保持冻结数据类语义。

**验证：** 使用 `uv run python -c` 构造合法与非法 Section，期望合法值被规范化、非法值抛出 `ValueError`。

### T16：补齐其余 Prompt 数据类型

**文件：** `mewcode/prompting/types.py`
**依赖：** T15

**步骤：**

1. 定义 `EnvironmentSnapshot`、`PromptOptions` 和 `PromptPackage`。
2. 为三个可选槽提供批准的默认值。
3. 保留 `Path`、`date`、`ToolDefinition` 的明确类型。

**验证：** `uv run python -m compileall mewcode/prompting/types.py` 通过，三种数据类可用批准的最小参数构造。

### T17：建立 Prompt 类型契约测试

**文件：** `tests/test_prompting.py`
**依赖：** T16

**步骤：**

1. 测试枚举值、冻结语义和默认值。
2. 测试空白规范化及非法 Section。
3. 测试 `PromptPackage` 保留工具顺序。

**验证：** `uv run pytest tests/test_prompting.py -q -k 'type or section or frozen'` 通过。

### T18：写入七个固定模块

**文件：** `mewcode/prompting/sections.py`
**依赖：** T16

**步骤：**

1. 原样写入 `plan.md` 批准的七段英文文案。
2. 使用批准的名称、Priority 和 `CACHEABLE` Channel。
3. 不在该文件读取环境、配置或项目文件。

**验证：** `uv run python -m compileall mewcode/prompting/sections.py` 通过。

### T19：写入三种模式提醒

**文件：** `mewcode/prompting/sections.py`
**依赖：** T18

**步骤：**

1. 原样写入 execute、plan、do 的完整文案。
2. 原样写入三种精简文案。
3. 提供按模式键取得成对文案的内部入口。

**验证：** `uv run python -c` 遍历三个模式，期望每个模式都有非空完整和精简版本。

### T20：测试固定目录与模式文案

**文件：** `tests/test_prompting.py`
**依赖：** T18–T19

**步骤：**

1. 断言七个名称、Priority、Channel 和顺序完全匹配 Plan。
2. 断言 Tool Use 同时包含专用工具和编辑前读取规则。
3. 断言每个精简提醒短于对应完整提醒。

**验证：** `uv run pytest tests/test_prompting.py -q -k 'catalog or mode_text'` 通过。

### T21：实现工作目录、平台和 Shell 采集

**文件：** `mewcode/prompting/environment.py`
**依赖：** T16

**步骤：**

1. 规范化传入 workspace 为绝对路径。
2. 使用注入值或 `platform.system()` 获取平台，空值回退 `unknown`。
3. 使用注入值、`SHELL` 或 Windows `COMSPEC` 获取 Shell，缺失时回退 `unknown`。

**验证：** `uv run python -m compileall mewcode/prompting/environment.py` 通过。

### T22：实现日期与时区回退

**文件：** `mewcode/prompting/environment.py`
**依赖：** T21

**步骤：**

1. 使用注入的 aware datetime 或本地当前时间生成日期。
2. 按“注入时区 → TZ → 本地时区名 → UTC offset → unknown”解析时区。
3. 只返回批准的五个字段。

**验证：** 固定 aware datetime 的 `uv run python -c` 输出预期 ISO 日期和时区。

### T23：测试环境采集边界

**文件：** `tests/test_prompting.py`
**依赖：** T21–T22

**步骤：**

1. 测试注入值、POSIX/Windows Shell 回退和 unknown。
2. 测试日期与时区优先级。
3. 用 monkeypatch 证明采集过程未调用 Git、仓库遍历或网络入口。

**验证：** `uv run pytest tests/test_prompting.py -q -k environment` 通过。

### T24：实现固定 Section 渲染

**文件：** `mewcode/prompting/builder.py`
**依赖：** T18

**步骤：**

1. 将单个 Section 渲染为 `## Name` 加内容。
2. 过滤 `CACHEABLE` Section 并按 Priority 排序。
3. 使用恰好一个空行拼接稳定提示。

**验证：** 使用固定两个 Section 的 `uv run python -c` 输出，期望标题顺序和 `\n\n` 分隔正确。

### T25：测试稳定提示顺序与空白

**文件：** `tests/test_prompting.py`
**依赖：** T24

**步骤：**

1. 断言七个固定模块按批准顺序出现一次。
2. 断言模块间恰好一个空行。
3. 断言相同输入得到字节级相同结果。

**验证：** `uv run pytest tests/test_prompting.py -q -k stable_render` 通过。

### T26：构造环境和可选动态 Section

**文件：** `mewcode/prompting/builder.py`
**依赖：** T16、T22、T24

**步骤：**

1. 按批准格式构造 Environment Section。
2. 省略空白自定义指令、Skill 和长期记忆。
3. 保持非空 Skill 顺序，并以一个空行合并。

**验证：** `uv run pytest tests/test_prompting.py -q -k 'optional or skill or environment_section'` 通过。

### T27：实现保留标签校验

**文件：** `mewcode/prompting/builder.py`
**依赖：** T26

**步骤：**

1. 检查所有动态字段中的 `<system-reminder` 和 `</system-reminder>`。
2. 命中任一保留片段时抛出明确、无敏感内容的 `ValueError`。
3. 不对已批准固定提示中的说明性标签误报。

**验证：** `uv run pytest tests/test_prompting.py -q -k reminder_injection` 通过。

### T28：实现系统补充消息渲染

**文件：** `mewcode/prompting/builder.py`
**依赖：** T19、T26–T27

**步骤：**

1. 生成唯一一对 `<system-reminder>` 外层标签。
2. 固定写入静默处理声明、Active Mode 和 Environment。
3. 按 Priority 追加非空动态与额外 Section，Section 间保留一个空行。

**验证：** `uv run pytest tests/test_prompting.py -q -k supplemental_render` 通过。

### T29：实现工具定义防御性快照

**文件：** `mewcode/prompting/builder.py`
**依赖：** T24

**步骤：**

1. 验证工具名称非空且不重复。
2. 递归复制每个 `ToolDefinition.input_schema`。
3. 保持工具列表原始顺序，后续只读取私有快照。

**验证：** 修改原始嵌套 Schema 后运行聚焦测试，期望快照内容不变。

### T30：实现规范化缓存身份

**文件：** `mewcode/prompting/builder.py`
**依赖：** T24、T29

**步骤：**

1. 构造包含版本、稳定提示和工具列表的规范对象。
2. 使用键排序、紧凑分隔符和 UTF-8 编码。
3. 返回 SHA-256 的 64 位十六进制摘要。

**验证：** 固定输入连续计算两次得到相同 64 位摘要。

### T31：测试缓存身份边界

**文件：** `tests/test_prompting.py`
**依赖：** T29–T30

**步骤：**

1. 测试对象键顺序不影响哈希。
2. 测试工具顺序、描述、Schema 或稳定模块变化会改变哈希。
3. 测试环境、模式、轮次和三个可选槽变化不改变哈希。

**验证：** `uv run pytest tests/test_prompting.py -q -k cache_identity` 通过。

### T32：实现 RunPrompt 轮次选择

**文件：** `mewcode/prompting/builder.py`
**依赖：** T28、T30

**步骤：**

1. 定义冻结的 `RunPrompt`。
2. 在 `for_iteration()` 中拒绝小于 1 的轮次。
3. 用 `(iteration - 1) % 5 == 0` 选择完整提醒，并返回新的 `PromptPackage`。

**验证：** 固定 RunPrompt 在第 1、6、11 轮选择完整文案，第 2、5、7 轮选择精简文案。

### T33：测试 RunPrompt 不变量

**文件：** `tests/test_prompting.py`
**依赖：** T32

**步骤：**

1. 覆盖第 1–11 轮的完整/精简频率。
2. 断言稳定提示、工具和缓存身份跨轮次不变。
3. 断言补充消息每轮只有一对标签且 `RunPrompt` 未被修改。

**验证：** `uv run pytest tests/test_prompting.py -q -k run_prompt` 通过。

### T34：实现 PromptBuilder 主入口

**文件：** `mewcode/prompting/builder.py`
**依赖：** T24–T32

**步骤：**

1. 未传固定目录时使用七个批准模块。
2. 验证必需模块、唯一名称、唯一 Priority、模式和通道。
3. 组合固定、环境、可选及 extra Sections，返回一次性 `RunPrompt`。

**验证：** `uv run pytest tests/test_prompting.py -q -k prepare_run` 通过。

### T35：测试扩展 Section 与构建失败

**文件：** `tests/test_prompting.py`
**依赖：** T34

**步骤：**

1. 测试额外 CACHEABLE 与 SUPPLEMENTAL Section 各进入正确通道。
2. 测试重复名称、重复 Priority、缺少必需模块和非法模式。
3. 断言构建失败不返回部分 Prompt。

**验证：** `uv run pytest tests/test_prompting.py -q -k 'extra_section or invalid_builder'` 通过。

### T36：建立 Prompting 公开入口

**文件：** `mewcode/prompting/__init__.py`
**依赖：** T16、T22、T34

**步骤：**

1. 只导出 Plan 批准的数据类型、Builder、RunPrompt 和环境采集入口。
2. 不导出内部文案映射或渲染帮助函数。
3. 确保模块不导入 `mewcode.agent` 或具体 Provider。

**验证：** `uv run python -c 'from mewcode.prompting import PromptBuilder, RunPrompt, PromptOptions, capture_environment'` 通过。

### T37：运行 Prompting 聚焦回归

**文件：** `mewcode/prompting/*`、`tests/test_prompting.py`
**依赖：** T14–T36

**步骤：**

1. 运行完整 Prompting 测试。
2. 运行新包 compileall。
3. 检查文件中无项目指令加载、网络请求或仓库扫描代码。

**验证：** `uv run pytest tests/test_prompting.py -q` 与 `uv run python -m compileall mewcode/prompting tests/test_prompting.py` 均通过。

### T38：提交 Prompting 核心

**文件：** `mewcode/prompting/*`、`tests/test_prompting.py`
**依赖：** T37

**步骤：**

1. 只暂存 Prompting 包及其测试。
2. 创建一个 Prompting 核心逻辑提交。
3. 确认其他阶段文件未混入。

**验证：** `git show --stat --oneline -1` 仅列出 Prompting 包和 `tests/test_prompting.py`。

## 阶段 C：统一请求契约与 Agent 接入

### T39：定义统一 ProviderRequest

**文件：** `mewcode/providers/base.py`
**依赖：** T38

**步骤：**

1. 导入 `PromptPackage`。
2. 定义冻结的 `ProviderRequest`，只包含 tuple 历史和当轮 Prompt。
3. 不把取消令牌、运行 ID 或 iteration 放入请求数据。

**验证：** `uv run python -c 'from mewcode.providers.base import ProviderRequest'` 通过。

### T40：扩展五维 TokenUsage

**文件：** `mewcode/providers/base.py`
**依赖：** T39

**步骤：**

1. 在现有三个字段后加入 `cache_read_input_tokens`。
2. 加入 `cache_write_input_tokens`。
3. 两个新字段默认均为 `None`，保留现有三参数构造方式。

**验证：** `uv run python -c 'from mewcode.providers.base import TokenUsage; assert TokenUsage(1, 2, 3).cache_read_input_tokens is None'` 通过。

### T41：迁移 LLMProvider 协议

**文件：** `mewcode/providers/base.py`
**依赖：** T39–T40

**步骤：**

1. 将 `stream_response()` 的位置参数收敛为一个 `ProviderRequest`。
2. 保留关键字参数 `cancellation`。
3. 删除协议中的独立 history、tools 和 instructions 参数。

**验证：** `uv run python -m compileall mewcode/providers/base.py` 通过。

### T42：更新 Provider 公共导出

**文件：** `mewcode/providers/__init__.py`
**依赖：** T41

**步骤：**

1. 导入并导出 `ProviderRequest`。
2. 保持现有事件类型和工厂导出不变。
3. 检查 `__all__` 不暴露 Provider 内部缓存帮助函数。

**验证：** `uv run python -c 'from mewcode.providers import ProviderRequest, TokenUsage'` 通过。

### T43：让 ResponseCollector 接收统一请求

**文件：** `mewcode/agent/collector.py`
**依赖：** T41

**步骤：**

1. 将 `collect()` 的前三个请求参数替换为一个 `ProviderRequest`。
2. 原样把请求和取消令牌传给 Provider。
3. 保留文本背压、工具聚合、completed 校验和回退 ID 行为。

**验证：** `uv run python -m compileall mewcode/agent/collector.py` 通过。

### T44：迁移 Collector 契约测试

**文件：** `tests/test_agent_collector.py`
**依赖：** T43

**步骤：**

1. 用最小 `PromptPackage` 构造冻结的 `ProviderRequest`。
2. 让 FakeProvider 记录统一请求和独立取消令牌。
3. 断言 Collector 不改写 Prompt、历史或现有事件语义。

**验证：** `uv run pytest tests/test_agent_collector.py -q` 通过。

### T45：删除 AgentRequest 自由文本指令

**文件：** `mewcode/agent/types.py`
**依赖：** T38

**步骤：**

1. 删除 `AgentRequest.instructions`。
2. 保持 mode、user_content、tool_scope 和 source_plan_id 的批准顺序。
3. 保持数据类冻结语义。

**验证：** `uv run python -m compileall mewcode/agent/types.py` 通过。

### T46：更新 AgentRequest 类型测试

**文件：** `tests/test_agent_session.py`
**依赖：** T41、T45

**步骤：**

1. 让 ScriptedProvider 及其阻塞/取消变体接收并记录统一 `ProviderRequest`。
2. 用四个批准字段构造 execute、plan 和 do 请求，断言对象不存在 `instructions` 属性。
3. 保留模式、作用域、保存计划 ID 和冻结性断言。

**验证：** `uv run pytest tests/test_agent_session.py -q -k agent_request` 通过。

### T47：让 AgentRun 持有 RunPrompt

**文件：** `mewcode/agent/run.py`
**依赖：** T43、T45

**步骤：**

1. 用 `RunPrompt | None` 替换构造器中的独立工具序列。
2. 有效运行从 `RunPrompt.tools` 取得稳定快照；无效运行允许空值。
3. Scheduler 仍使用同一快照中的工具名称，不改变执行策略。

**验证：** `uv run python -m compileall mewcode/agent/run.py` 通过。

### T48：逐轮构造 ProviderRequest

**文件：** `mewcode/agent/run.py`
**依赖：** T47

**步骤：**

1. 每轮调用 `RunPrompt.for_iteration(iteration)`。
2. 用当时的 tuple 历史和新 `PromptPackage` 构造 `ProviderRequest`。
3. 把统一请求交给 Collector，不再读取 `AgentRequest.instructions`。

**验证：** `uv run python -m compileall mewcode/agent/run.py` 通过。

### T49：迁移 AgentRun 测试夹具并测试轮次频率

**文件：** `tests/test_agent_run.py`
**依赖：** T48

**步骤：**

1. 建立固定 `RunPrompt` 帮助函数，将现有 `AgentRun` 构造迁移到新契约。
2. 让 ScriptedCollector 记录每轮 `ProviderRequest`。
3. 覆盖第 1–6 轮完整/精简频率、稳定前缀复用及新运行重置。

**验证：** `uv run pytest tests/test_agent_run.py -q -k 'iteration_prompt or run_started'` 通过。

### T50：测试历史与补充消息隔离

**文件：** `tests/test_agent_run.py`
**依赖：** T49

**步骤：**

1. 构造至少两轮含工具反馈的运行。
2. 断言第二轮历史依次包含用户、助手和工具结果。
3. 断言任何历史消息都不等于或包含当轮 `system_supplement`。

**验证：** `uv run pytest tests/test_agent_run.py -q -k supplement_history` 通过。

### T51：实现五维 Usage 累计

**文件：** `mewcode/agent/run.py`
**依赖：** T48

**步骤：**

1. 将运行初始累计值的五个维度都设为零。
2. 扩展 `_add_usage()`，分别累计缓存读取和写入量。
3. 任一维度遇到 `None` 后保持 `None`，不影响其他维度。

**验证：** `uv run python -m compileall mewcode/agent/run.py` 通过。

### T52：测试五维 Usage 事件链

**文件：** `tests/test_agent_run.py`
**依赖：** T49、T51

**步骤：**

1. 使用正数、零和 `None` 组合构造三轮 Usage。
2. 断言 `UsageReported.current` 原样保留五维值。
3. 断言累计逐维求和，未知维度不可恢复为已知。

**验证：** `uv run pytest tests/test_agent_run.py -q -k usage` 通过。

### T53：注入 Session 的 Prompt 依赖

**文件：** `mewcode/agent/session.py`
**依赖：** T36、T45、T47

**步骤：**

1. 定义 `EnvironmentFactory`，并向构造器加入 Builder、环境工厂和 Options 三个可选关键字参数。
2. 默认使用七模块 `PromptBuilder`、基于当前目录的环境工厂及空 `PromptOptions`。
3. 删除三条旧模式指令常量，不从 Agent 反向管理提示文案。

**验证：** `uv run python -m compileall mewcode/agent/session.py` 通过。

### T54：重排有效请求创建事务

**文件：** `mewcode/agent/session.py`
**依赖：** T53

**步骤：**

1. 依次完成命令解析、作用域工具筛选、环境采集和 `prepare_run()`。
2. 将 `RunMode.value`、固定环境、Options 和确定性工具定义交给 Builder。
3. 仅在 Prompt 构建成功后提交用户消息，再用同一 `RunPrompt` 创建运行。

**验证：** `uv run pytest tests/test_agent_session.py -q -k 'command_parser or tool_scope'` 通过。

### T55：保持无效命令短路

**文件：** `mewcode/agent/session.py`
**依赖：** T54

**步骤：**

1. 无效命令使用不带 instructions 的 `AgentRequest`。
2. 创建允许 `RunPrompt` 为空的无效运行。
3. 确保该路径不查询工具、不采集环境、不调用 Builder 且不提交历史。

**验证：** `uv run pytest tests/test_agent_session.py -q -k invalid` 通过。

### T56：测试 Prompt 失败的提交边界

**文件：** `tests/test_agent_session.py`
**依赖：** T54–T55

**步骤：**

1. 注入失败的环境工厂，断言历史保持不变且 Provider 未调用。
2. 注入抛出 `ValueError` 的 Builder，断言历史保持不变且无活动运行。
3. 断言错误不会泄露动态字段内容。

**验证：** `uv run pytest tests/test_agent_session.py -q -k prompt_failure` 通过。

### T57：测试运行级环境、模式和工具快照

**文件：** `tests/test_agent_session.py`
**依赖：** T54

**步骤：**

1. 注入固定环境与 Options，覆盖 execute、plan 和 do 三种模式。
2. 断言每个新运行只采集一次环境，并把 `RunMode.value` 交给 Builder。
3. 断言 plan 只快照只读工具，execute/do 保持注册顺序。

**验证：** `uv run pytest tests/test_agent_session.py -q -k 'prompt_snapshot or environment_factory'` 通过。

### T58：在 CLI 绑定固定 Workspace 环境

**文件：** `mewcode/cli.py`
**依赖：** T53–T54

**步骤：**

1. 在启动时确定 workspace 后创建默认 `PromptBuilder`。
2. 注入始终基于该 workspace 的环境工厂，而非后续变化的进程目录。
3. 注入空 `PromptOptions`，不加载项目指令、Skill 或记忆。

**验证：** `uv run python -m compileall mewcode/cli.py` 通过。

### T59：迁移 CLI Provider 测试替身

**文件：** `tests/test_cli.py`
**依赖：** T41、T58

**步骤：**

1. 让 FakeProvider 接收并记录 `ProviderRequest`。
2. 断言 Prompt 环境中的工作目录等于 CLI 启动时 workspace。
3. 断言工具顺序不变，三个可选 Section 未凭空出现。

**验证：** `uv run pytest tests/test_cli.py -q` 通过。

### T60：运行 Agent 接入聚焦回归

**文件：** `mewcode/providers/base.py`、`mewcode/agent/*`、`mewcode/cli.py`、相关测试
**依赖：** T39–T59

**步骤：**

1. 运行 Provider 基础契约、Collector、Session、Run 和 CLI 测试。
2. 编译 Provider 基础、Agent 和 CLI 模块。
3. 搜索并清除生产代码中旧 `instructions=` 调用和三条模式常量。

**验证：** `uv run pytest tests/test_agent_collector.py tests/test_agent_events.py tests/test_agent_run.py tests/test_agent_session.py tests/test_cli.py -q` 与 `uv run python -m compileall mewcode/providers/base.py mewcode/agent mewcode/cli.py` 均通过；`rg -n 'EXECUTE_INSTRUCTIONS|PLAN_INSTRUCTIONS|DO_INSTRUCTIONS|request\.instructions' mewcode` 无匹配。

### T61：提交统一请求与 Agent 接入

**文件：** `mewcode/providers/{base,__init__}.py`、`mewcode/agent/{types,session,run,collector}.py`、`mewcode/cli.py`、对应测试
**依赖：** T60

**步骤：**

1. 只暂存本阶段明确修改的生产和测试文件。
2. 创建一个统一请求与 Agent 接入提交。
3. 确认 Provider 具体适配器、工具描述和用户原有文档未混入。

**验证：** `git show --stat --oneline -1` 仅显示阶段 C 文件；`git status --short` 保留未进入本提交的文件。

## 阶段 D：双 Provider 缓存适配

### T62：实现缓存提示不支持分类器

**文件：** `mewcode/providers/cache.py`
**依赖：** T61

**步骤：**

1. 提供接收 HTTP 状态、结构化错误体和目标字段名的内部分类入口。
2. 只接受 400/422，且错误结构明确关联 `prompt_cache_key` 或 `cache_control` 的不支持语义。
3. 对纯文本猜测、认证、限流、模型错误、网络错误和未知结构返回 false。

**验证：** `uv run python -m compileall mewcode/providers/cache.py` 通过。

### T63：测试缓存错误分类矩阵

**文件：** `tests/test_providers.py`
**依赖：** T62

**步骤：**

1. 覆盖 400 和 422 的明确字段不支持错误。
2. 覆盖同状态但无目标字段、目标字段普通校验失败及 401/403/429/500。
3. 覆盖畸形 JSON、纯文本和包含 API Key 的错误，断言不误分类且不输出秘密。

**验证：** `uv run pytest tests/test_providers.py -q -k cache_hint_classifier` 通过。

### T64：映射 OpenAI 稳定与动态通道

**文件：** `mewcode/providers/openai.py`
**依赖：** T41、T62

**步骤：**

1. 让 `stream_response()` 接收 `ProviderRequest`。
2. 将稳定提示放入 `instructions`，将动态补充作为历史前的 system input item。
3. 按快照顺序序列化工具，并加入 `prompt_cache_key` 和 stream 标记。

**验证：** `uv run python -m compileall mewcode/providers/openai.py` 通过。

### T65：测试 OpenAI 请求体边界

**文件：** `tests/test_providers.py`
**依赖：** T64

**步骤：**

1. 断言 instructions 仅等于稳定提示，input 首项是 system supplement。
2. 断言后续历史顺序、工具顺序和 `prompt_cache_key` 精确匹配请求快照。
3. 断言动态环境、模式和历史不泄漏进稳定提示或缓存键。

**验证：** `uv run pytest tests/test_providers.py -q -k openai_prompt_mapping` 通过。

### T66：严格解析 OpenAI 五维 Usage

**文件：** `mewcode/providers/openai.py`
**依赖：** T40、T64

**步骤：**

1. 映射三个现有字段、`cached_tokens` 和可选 `cache_write_tokens`。
2. 路径缺失时返回 `None`，显式零值保持零。
3. 显式存在但不是非负整数时抛出脱敏的 `ProviderError`。

**验证：** `uv run python -m compileall mewcode/providers/openai.py` 通过。

### T67：测试 OpenAI Usage 缺失、零值与非法值

**文件：** `tests/test_providers.py`
**依赖：** T66

**步骤：**

1. 覆盖五维正数、零值和逐路径缺失。
2. 覆盖布尔、负数、浮点和字符串非法值。
3. 断言非法 completed 不返回完成事件，缺失缓存字段不使成功响应失败。

**验证：** `uv run pytest tests/test_providers.py -q -k openai_usage` 通过。

### T68：实现 OpenAI 单次缓存降级

**文件：** `mewcode/providers/openai.py`
**依赖：** T62、T64

**步骤：**

1. 首次建立流时携带 `prompt_cache_key`。
2. 仅在首个事件前被分类器确认不支持时，构造只删除该字段的新请求体并重试一次。
3. 不修改原始 `ProviderRequest`、Prompt、历史、工具或取消令牌。

**验证：** `uv run python -m compileall mewcode/providers/openai.py` 通过。

### T69：测试 OpenAI 降级成功路径

**文件：** `tests/test_providers.py`
**依赖：** T68

**步骤：**

1. 分别模拟明确的 400 和 422 不支持响应后成功流。
2. 断言恰好两次 HTTP 请求，第二次只缺少 `prompt_cache_key`。
3. 断言最终事件、稳定提示、动态补充、历史和工具与首次请求一致。

**验证：** `uv run pytest tests/test_providers.py -q -k openai_cache_fallback_success` 通过。

### T70：测试 OpenAI 不重试边界

**文件：** `tests/test_providers.py`
**依赖：** T68

**步骤：**

1. 覆盖认证、限流、模型、网络和非缓存 400/422 错误只请求一次。
2. 覆盖已收到文本或工具事件后的错误绝不重试。
3. 覆盖取消优先及错误脱敏，确认 API Key 不出现在异常文本。

**验证：** `uv run pytest tests/test_providers.py -q -k 'openai_cache_no_retry or openai_cache_redaction'` 通过。

### T71：运行 OpenAI 聚焦回归

**文件：** `mewcode/providers/openai.py`、`tests/test_providers.py`
**依赖：** T65、T67、T69–T70

**步骤：**

1. 运行所有 OpenAI 请求、流事件、工具和错误测试。
2. 检查 successful completed 后无额外事件。
3. 检查测试 HTTP 载荷不访问真实网络。

**验证：** `uv run pytest tests/test_providers.py -q -k openai` 通过。

### T72：映射 Anthropic 双 System Block

**文件：** `mewcode/providers/anthropic.py`
**依赖：** T41、T62

**步骤：**

1. 让 `stream_response()` 接收 `ProviderRequest`。
2. 将稳定提示放入第一个带 ephemeral 的 text block，将动态补充放入第二个无缓存标记的 block。
3. 有工具时只给最后一个工具加 ephemeral；无工具时不构造空工具或伪造断点。

**验证：** `uv run python -m compileall mewcode/providers/anthropic.py` 通过。

### T73：测试 Anthropic 请求体边界

**文件：** `tests/test_providers.py`
**依赖：** T72

**步骤：**

1. 断言两个 system block 的顺序、文本和缓存标记精确匹配 Plan。
2. 覆盖零个、一个和多个工具，只允许最后一个工具带标记。
3. 断言消息历史不含补充系统消息，thinking 配置和现有历史合并行为不回归。

**验证：** `uv run pytest tests/test_providers.py -q -k anthropic_prompt_mapping` 通过。

### T74：严格累计 Anthropic 流式 Usage

**文件：** `mewcode/providers/anthropic.py`
**依赖：** T40、T72

**步骤：**

1. 从 message_start 映射输入、缓存读取和缓存创建量。
2. 从 message_delta 映射输出量，`total_tokens` 保持 `None`。
3. 后续事件缺失字段时保留已观测值；显式非法字段抛出脱敏 `ProviderError`。

**验证：** `uv run python -m compileall mewcode/providers/anthropic.py` 通过。

### T75：测试 Anthropic Usage 流式边界

**文件：** `tests/test_providers.py`
**依赖：** T74

**步骤：**

1. 覆盖缓存读取/创建正数、零值和缺失。
2. 覆盖多次 usage 事件中后续缺失不覆盖已知值。
3. 覆盖五类非法值，断言不产生不完整完成事件。

**验证：** `uv run pytest tests/test_providers.py -q -k anthropic_usage` 通过。

### T76：实现 Anthropic 单次缓存降级

**文件：** `mewcode/providers/anthropic.py`
**依赖：** T62、T72

**步骤：**

1. 首次建立流时保留 system 和最后工具的 `cache_control`。
2. 仅在首个事件前被分类器确认不支持时，递归复制请求体并只删除所有 `cache_control` 后重试一次。
3. 保持原始请求、工具 Schema、system 文本、历史和 thinking 选项不变。

**验证：** `uv run python -m compileall mewcode/providers/anthropic.py` 通过。

### T77：测试 Anthropic 降级成功路径

**文件：** `tests/test_providers.py`
**依赖：** T76

**步骤：**

1. 分别模拟明确的 400 和 422 cache_control 不支持响应后成功流。
2. 断言恰好重试一次，第二次所有 cache_control 均移除。
3. 断言其余请求 JSON 和最终 Provider 事件不变。

**验证：** `uv run pytest tests/test_providers.py -q -k anthropic_cache_fallback_success` 通过。

### T78：测试 Anthropic 不重试边界

**文件：** `tests/test_providers.py`
**依赖：** T76

**步骤：**

1. 覆盖认证、限流、模型、网络和非缓存 400/422 错误只请求一次。
2. 覆盖收到任意流事件后错误不重试。
3. 覆盖取消、API Key 脱敏和原始嵌套工具 Schema 未被修改。

**验证：** `uv run pytest tests/test_providers.py -q -k 'anthropic_cache_no_retry or anthropic_cache_redaction'` 通过。

### T79：运行 Anthropic 聚焦回归

**文件：** `mewcode/providers/anthropic.py`、`tests/test_providers.py`
**依赖：** T73、T75、T77–T78

**步骤：**

1. 运行所有 Anthropic 请求、流事件、工具和错误测试。
2. 检查 completed、取消和历史合并协议保持不变。
3. 检查测试响应均由本地替身提供。

**验证：** `uv run pytest tests/test_providers.py -q -k anthropic` 通过。

### T80：验证双 Provider 统一端到端契约

**文件：** `tests/test_providers.py`
**依赖：** T71、T79

**步骤：**

1. 用同一 `ProviderRequest` 参数化运行 OpenAI 与 Anthropic 模拟端到端场景。
2. 覆盖文本、工具调用、工具反馈历史和五维 Usage。
3. 断言 Provider 差异只存在于 HTTP 映射，Agent 可见事件一致。

**验证：** `uv run pytest tests/test_providers.py -q -k provider_request_e2e` 通过。

### T81：提交双 Provider 缓存适配

**文件：** `mewcode/providers/{cache,openai,anthropic}.py`、`tests/test_providers.py`
**依赖：** T80

**步骤：**

1. 运行完整 Provider 测试后只暂存本阶段文件。
2. 创建一个双 Provider 缓存适配提交。
3. 确认没有凭据、原始实网响应或工具/界面文件混入。

**验证：** `uv run pytest tests/test_providers.py -q` 通过；`git show --stat --oneline -1` 仅显示阶段 D 文件。

## 阶段 E：工具强化、Usage 与双界面

### T82：更新三个文件工具描述

**文件：** `mewcode/tools/file_tools.py`
**依赖：** T81

**步骤：**

1. 原样写入 Plan 批准的 read_file 描述。
2. 原样写入 write_file 和 edit_file 描述。
3. 不修改名称、Schema、权限、确认或执行策略。

**验证：** `uv run python -m compileall mewcode/tools/file_tools.py` 通过。

### T83：更新搜索与命令工具描述

**文件：** `mewcode/tools/search_tools.py`、`mewcode/tools/command.py`
**依赖：** T81

**步骤：**

1. 原样写入 glob_files 和 search_code 描述。
2. 原样写入 run_command 的专用工具兜底描述。
3. 不修改任何运行时行为或注册顺序。

**验证：** `uv run python -m compileall mewcode/tools/search_tools.py mewcode/tools/command.py` 通过。

### T84：锁定六个稳定工具定义

**文件：** `tests/test_tool_registry.py`
**依赖：** T82–T83

**步骤：**

1. 断言六个工具描述与 Plan 字节级一致。
2. 断言名称、Schema、作用域过滤和默认注册顺序未变化。
3. 断言任一描述变化会通过 Prompting 测试改变缓存身份。

**验证：** `uv run pytest tests/test_tool_registry.py tests/test_prompting.py -q -k 'description or cache_identity'` 通过。

### T85：扩展共享 usage_text

**文件：** `mewcode/tui/presentation.py`
**依赖：** T40

**步骤：**

1. 保留 in、out 和 total 的现有格式。
2. current 与 cumulative 分别在缓存字段非 `None` 时追加 cache-read/cache-write。
3. 显式零值必须显示，不增加卡片、事件或 Provider 判断。

**验证：** `uv run python -m compileall mewcode/tui/presentation.py` 通过。

### T86：建立 Usage 文本单元测试

**文件：** `tests/test_tui_presentation.py`
**依赖：** T85

**步骤：**

1. 覆盖两个缓存字段都缺失时完全省略标签。
2. 覆盖零值、正值和 current/cumulative 不同可用性。
3. 断言现有三维文本格式不回归。

**验证：** `uv run pytest tests/test_tui_presentation.py -q` 通过。

### T87：迁移全屏 TUI 测试 Provider

**文件：** `tests/test_tui_app.py`
**依赖：** T41、T85

**步骤：**

1. 让 ScriptedProvider 和 RecoveringProvider 接收统一 `ProviderRequest`。
2. 保留阻塞、恢复、取消和事件脚本行为。
3. 新增含 cache-read/cache-write 的 Usage 事件，断言全屏界面显示共享文本。

**验证：** `uv run pytest tests/test_tui_app.py -q -k 'usage or provider'` 通过。

### T88：迁移纯文本 TUI 测试 Provider

**文件：** `tests/test_tui_plain.py`
**依赖：** T41、T85

**步骤：**

1. 让纯文本 ScriptedProvider 接收统一 `ProviderRequest`。
2. 覆盖 cache-read 为零和 cache-write 为正数的输出。
3. 覆盖字段缺失时不出现对应标签，并保持非 TTY/StringIO 路径。

**验证：** `uv run pytest tests/test_tui_plain.py -q -k usage` 通过。

### T89：验证双界面共享格式

**文件：** `tests/test_tui_app.py`、`tests/test_tui_plain.py`、`tests/test_tui_presentation.py`
**依赖：** T86–T88

**步骤：**

1. 向两种界面发送相同 `UsageReported`。
2. 断言二者可见 Token 文本等于 `usage_text()` 的同一结果。
3. 断言 app.py 和 plain.py 未新增 Provider 协议分支。

**验证：** `uv run pytest tests/test_tui_app.py tests/test_tui_plain.py tests/test_tui_presentation.py -q -k shared_usage` 通过。

### T90：更新 Usage 事件公共契约测试

**文件：** `tests/test_agent_events.py`
**依赖：** T40

**步骤：**

1. 用五维 current 和 cumulative 构造 `UsageReported`。
2. 断言两个缓存字段通过事件原样可见。
3. 保留事件联合类型、冻结性和序列字段断言。

**验证：** `uv run pytest tests/test_agent_events.py -q` 通过。

### T91：运行工具与界面聚焦回归

**文件：** 阶段 E 全部生产和测试文件
**依赖：** T84、T89–T90

**步骤：**

1. 运行工具注册、Usage 呈现、全屏和纯文本测试。
2. 编译工具与 TUI 包。
3. 搜索生产 UI，确认缓存字段只由 `usage_text()` 格式化。

**验证：** `uv run pytest tests/test_tool_registry.py tests/test_tui_presentation.py tests/test_tui_app.py tests/test_tui_plain.py tests/test_agent_events.py -q` 与 `uv run python -m compileall mewcode/tools mewcode/tui` 均通过；`rg -n 'cache-read|cache-write' mewcode/tui` 只命中 `presentation.py`。

### T92：提交工具强化与 Usage 界面

**文件：** 三个工具文件、`mewcode/tui/presentation.py`、阶段 E 测试
**依赖：** T91

**步骤：**

1. 只暂存工具描述、共享 Usage 格式和对应测试。
2. 创建一个工具强化与 Usage 呈现提交。
3. 确认 app.py/plain.py 生产文件未产生无必要改动，用户文档未混入。

**验证：** `git show --stat --oneline -1` 仅显示阶段 E 文件。

## 阶段 F：候选评估与最终验证

### T93：记录候选版本元数据

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T92

**步骤：**

1. 记录候选提交、与基线相同的 Provider、模型和执行日期。
2. 重建非敏感临时工作区，确保初始输入与基线一致。
3. 只记录配置名称和相对样例，不复制凭据或完整配置。

**验证：** 候选元数据行均非空，且基线/候选的模型与场景版本可以直接对照。

### T94：运行候选“专用搜索工具”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T93

**步骤：**

1. 提交与基线相同的代码查找与解释输入。
2. 记录实际工具顺序及是否使用 run_command 替代搜索工具。
3. 填写改善、持平或退化，不改动评估标准。

**验证：** 对应候选行包含固定输入版本、实际工具序列和对比结论。

### T95：运行候选“局部编辑前读取”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T94

**步骤：**

1. 恢复与基线一致的已有文件内容。
2. 提交相同局部替换请求并记录调用顺序。
3. 明确比较同一路径 read_file 是否先于 edit_file。

**验证：** 对应候选行包含相对路径、工具顺序、“先读/未先读”和对比等级。

### T96：运行候选“完整替换已有文件”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T95

**步骤：**

1. 恢复与基线一致的完整替换样例。
2. 记录 read_file 与 write_file 的顺序。
3. 记录是否错误使用 Shell 直接写入并填写对比结果。

**验证：** 对应候选行包含调用顺序、专用工具判断和对比等级。

### T97：运行候选“创建新文件”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T96

**步骤：**

1. 确认与基线同名的临时相对路径不存在。
2. 提交相同创建请求。
3. 记录是否直接使用 write_file 以及是否发生无意义读取。

**验证：** 对应候选行包含工具序列、文件创建结果和对比等级；临时文件不进入仓库。

### T98：运行候选“聚焦测试命令”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T97

**步骤：**

1. 提交与基线相同的安全测试命令请求。
2. 记录 run_command 选择、确认过程和实际结果。
3. 比较是否出现不适用的专用工具替代或绕过确认。

**验证：** 对应候选行包含命令类别、确认行为、结果和对比等级。

### T99：运行候选“规划模式只读”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T98

**步骤：**

1. 使用与基线相同的 `/plan` 输入。
2. 记录工具访问、是否发生修改及计划是否基于观察。
3. 将任何写入、命令执行或越权行为标记为硬性失败。

**验证：** 对应候选行明确记录只读性、计划可执行性和对比等级。

### T100：运行候选“至少六轮工具循环”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T99

**步骤：**

1. 使用与基线相同的长循环任务，尝试产生至少六次内部模型请求。
2. 记录实际 iteration、模式保持及是否复述 system-reminder。
3. 未达到六轮时如实标记未覆盖，不推断第 6 轮行为。

**验证：** 对应候选行包含实际 iteration、六轮覆盖状态、模式与标签观察。

### T101：运行候选“输出风格”场景

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T100

**步骤：**

1. 提交与基线相同的解释和总结输入。
2. 逐项记录是否结论先行、区分事实与建议、保持直接清晰。
3. 检查回答未暴露系统模块、环境注入、缓存身份或保留标签。

**验证：** 对应候选行包含所有固定观察项和对比等级。

### T102：完成行为对比与硬性失败审计

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T94–T101

**步骤：**

1. 为八个行为场景填完整改善/持平/退化和备注。
2. 逐项审计 Shell 替代、编辑前未读、标签复述、规划越权和秘密泄露。
3. 任一硬性失败存在时停止最终通过结论并记录待修项。

**验证：** 对比表无空白结论；硬性失败区明确写出“无”或具体失败证据。

### T103：执行首选 Provider 真实缓存验证

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T102

**步骤：**

1. 确认模型支持提示缓存，稳定前缀达到最低长度，且临时工作区无敏感数据。
2. 使用相同稳定提示、工具集合和顺序执行一次预热及最多两次不同用户问题的重复请求。
3. 记录三次以内的输入、输出、cache-read 和 cache-write 数字，不保存原始响应。

**验证：** 首选 Provider 表包含实际请求数、模型、稳定输入长度及每次可观测 Usage。

### T104：判定首选 Provider 缓存证据

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T103

**步骤：**

1. 若任一重复请求 cache-read 大于零，记录首选 Provider 通过。
2. 若未命中，停止继续向该 Provider 计费，并记录返回字段和可能原因。
3. 明确区分真实命中、零、不可观测和降级成功。

**验证：** 文档包含首选 Provider 的明确“通过”或“需备用 Provider”结论及证据行。

### T105：按条件执行备用 Provider 验证

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T104

**步骤：**

1. 首选已出现 cache-read 大于零时，记录“无需执行备用 Provider”并停止额外计费。
2. 首选未命中时，按相同前置条件在另一 Provider 执行一次预热和最多两次重复请求。
3. 记录 cache-read/cache-write、动态标签未泄露及是否发生缓存降级。

**验证：** 备用区要么有明确免执行理由，要么有不超过三次的完整脱敏记录。

### T106：执行真实缓存通过门

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T105

**步骤：**

1. 在两家实际执行过的 Provider 证据中查找至少一个重复请求的 cache-read 正数。
2. 确认 OpenAI 缺失写入量时未伪造 cache-write，Anthropic 返回创建量时正确显示。
3. 两家均无正数时将里程碑标记为未通过并停止完成声明，不以接口成功或降级代替命中。

**验证：** 最终缓存结论引用一条 `cache-read > 0` 的脱敏记录；若无该记录，结论必须保持未通过。

### T107：审计候选与实网记录安全

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T102、T106

**步骤：**

1. 删除 API Key、认证头、完整响应和敏感绝对路径。
2. 保留 Provider、模型、日期、提交、Usage 数字、行为结论和未解决问题。
3. 确认定性比较未宣称统计显著性。

**验证：** 人工逐行复核后运行 `rg -n 'Authorization:|x-api-key:|Bearer [A-Za-z0-9]' docs/05-system-prompt/manual-evaluation.md`，期望无匹配。

### T108：运行里程碑聚焦测试

**文件：** 本里程碑全部生产和测试文件
**依赖：** T92

**步骤：**

1. 运行 Prompting、Agent、Provider、工具和 TUI 相关测试文件。
2. 保留完整失败输出并先修复任何回归。
3. 重跑直至聚焦集合无失败。

**验证：** `uv run pytest tests/test_prompting.py tests/test_agent_collector.py tests/test_agent_events.py tests/test_agent_run.py tests/test_agent_session.py tests/test_cli.py tests/test_providers.py tests/test_tool_registry.py tests/test_tui_presentation.py tests/test_tui_app.py tests/test_tui_plain.py -q` 通过。

### T109：运行完整测试套件

**文件：** `mewcode/`、`tests/`
**依赖：** T108

**步骤：**

1. 运行完整 pytest。
2. 不使用跳过、放宽断言或真实网络规避失败。
3. 记录实际通过数量和 snapshot 数量。

**验证：** `uv run pytest` 零失败退出。

### T110：验证导入、编译与依赖锁

**文件：** `mewcode/`、`tests/`、`uv.lock`
**依赖：** T109

**步骤：**

1. 编译全部生产和测试模块。
2. 验证锁文件与项目元数据一致。
3. 从 Python 入口导入 Prompting、ProviderRequest 和 CLI。

**验证：** `uv run python -m compileall mewcode tests`、`uv lock --check` 和 `uv run python -c 'import mewcode.cli; from mewcode.prompting import PromptBuilder; from mewcode.providers import ProviderRequest'` 均通过。

### T111：验证格式、秘密与工作树边界

**文件：** 当前工作树
**依赖：** T110、T107

**步骤：**

1. 运行 diff 格式检查。
2. 检查新增内容无真实 API Key、认证头或完整敏感响应。
3. 确认 `docs/HARNESS_ARCHITECTURE.md` 仍是用户原有未跟踪文件且未被暂存。

**验证：** `git diff --check` 通过；`git diff --cached --name-only` 不含 `docs/HARNESS_ARCHITECTURE.md`；人工脱敏审计无发现。

### T112：验证架构与明确不做边界

**文件：** `mewcode/`、`docs/05-system-prompt/`
**依赖：** T110

**步骤：**

1. 确认 Prompting 不导入 Agent 或具体 Provider，Agent 只通过公开 Prompting 接口接入。
2. 确认消息历史没有新增持久 SystemMessage，SSE、Scheduler 和配置边界未修改。
3. 搜索并确认没有项目指令加载、自动记忆、真实 MCP、自动评分或 read-before-write 运行时拦截器。

**验证：** `git diff --name-only -- mewcode/messages.py mewcode/config.py mewcode/agent/scheduler.py mewcode/providers/sse.py` 无输出；`rg -n 'mewcode\.agent|mewcode\.providers\.(openai|anthropic)' mewcode/prompting` 无匹配；边界审计无额外功能。

### T113：验证模块与控制台启动

**文件：** `mewcode/cli.py`、包入口
**依赖：** T110

**步骤：**

1. 在没有配置文件的临时 HOME 和空目录分别启动模块入口与控制台脚本。
2. 断言二者均解析到当前项目并给出干净的配置缺失错误。
3. 确认错误中不包含缓存身份、系统提示或秘密。

**验证：** 保存 `repo_root=$PWD`，在 `tmp_home=$(mktemp -d)` 与 `tmp_cwd=$(mktemp -d)` 下分别执行 `(cd "$tmp_cwd" && HOME="$tmp_home" uv run --project "$repo_root" python -m mewcode)` 和 `(cd "$tmp_cwd" && HOME="$tmp_home" uv run --project "$repo_root" mewcode)`；两者均期望退出码 1、只显示配置缺失错误，且不出现 traceback 或内部提示内容。

### T114：记录最终验证证据

**文件：** `docs/05-system-prompt/manual-evaluation.md`
**依赖：** T106–T113

**步骤：**

1. 写入聚焦测试、完整测试、compileall、lock、diff 和启动验证的实际结果。
2. 写入真实缓存命中引用、行为对比结论和所有未解决问题。
3. 只有无硬性失败且存在 cache-read 正数证据时标记候选通过。

**验证：** 最终结论区包含命令、实际退出结果、缓存证据和明确通过/未通过状态。

### T115：提交候选评估与最终证据

**文件：** `docs/05-system-prompt/manual-evaluation.md` 及尚未提交的本里程碑修复文件
**依赖：** T114

**步骤：**

1. 复核所有尚未提交的差异只属于本里程碑。
2. 暂存脱敏后的评估记录和最终验证期间必要修复，创建最终逻辑提交。
3. 始终排除 `docs/HARNESS_ARCHITECTURE.md` 和任何临时评估工作区。

**验证：** `git show --stat --oneline -1` 只包含本里程碑文件；`git show --format= --name-only -1` 不含用户原有文档或临时文件。

### T116：执行提交后最终快照

**文件：** 当前仓库状态
**依赖：** T115

**步骤：**

1. 记录最终提交标识和分支状态。
2. 再次运行完整测试与 diff 检查，证明提交后快照可复现。
3. 确认不推送远端，工作树仅允许用户原有未跟踪文件。

**验证：** `uv run pytest` 与 `git diff --check` 通过；`git status --short` 只显示预先存在且明确排除的用户文件；最终报告记录提交标识和实际测试结果。

## 执行顺序

```text
T1 → T2 → ... → T13
                   ↓
T14 → T15 → ... → T38
                   ↓
T39 → T40 → ... → T61
                   ↓
T62 → T63 → ... → T81
                   ↓
T82 → T83 → ... → T92
                   ↓
T93 → T94 → ... → T104
                         ├─ 首选命中 → T105 记录免执行
                         └─ 首选未命中 → T105 验证备用 Provider
                                              ↓
T106 → T107 ────────────────────────────────┐
T108 → T109 → T110 → T111/T112/T113 ──────┤
                                             ↓
                                           T114 → T115 → T116
```

除 T105 的显式成本控制分支外，任务按编号和声明依赖执行。T106 是真实缓存硬门；没有 `cache-read > 0` 证据时不得进入“里程碑通过”结论。

## Plan 覆盖索引

| Plan 组件 | 对应任务 |
|---|---|
| 人工基线与安全记录 | T1–T13 |
| Prompting 类型、固定模块、环境、渲染、缓存身份与轮次 | T14–T38 |
| ProviderRequest、LLMProvider 与 Collector | T39–T44 |
| AgentRequest、AgentSession、AgentRun 与 CLI | T45–T61 |
| 缓存错误分类器 | T62–T63 |
| OpenAI 映射、Usage 与降级 | T64–T71 |
| Anthropic 映射、Usage 与降级 | T72–T79 |
| 双 Provider 契约 | T80–T81 |
| 六个工具描述 | T82–T84 |
| 五维 Usage、共享格式与双界面 | T40、T51–T52、T85–T92 |
| 候选定性对比 | T93–T102 |
| 真实缓存命中 | T103–T107 |
| 全量工程验证与提交 | T108–T116 |
