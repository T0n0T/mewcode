# MewCode Cyberpunk TUI Checklist

> 每项都通过运行代码、自动测试或观察终端行为验证。先记录实际证据，再勾选通过。

## 规格与范围

- [ ] spec.md、plan.md、task.md 和 checklist.md 均不存在未决标记、编码替换字符或未完成小节。（验证：`! rg -ni 'tb[d]|to[d]o|placeholde[r]' docs/03-cyberpunk-tui && ! LC_ALL=C rg -n $'\xEF\xBF\xBD' docs/03-cyberpunk-tui`）
- [ ] 实现只包含 TUI、回合展示事件和中断所需改动，没有新增斜杠命令、消息排队、Agent steering、模型切换、持久化历史或主题配置。（验证：检查 `git diff --stat` 和 `git diff`，逐项对照 spec“不做的事”）
- [ ] 配置文件字段、查找顺序和默认行为保持不变。（验证：`uv run pytest tests/test_config.py -q`，并确认 `config.yaml.example` 无无关修改）

## 全屏布局与视觉

- [ ] **AC1：** 交互式 TTY 启动后显示单列全屏界面，包含顶部栏、可滚动对话区、底部输入框和启动卡。（验证：运行 `uv run pytest tests/test_tui_app.py -q -k "mount or welcome"`，查看 120×36 快照）
- [ ] **AC2：** 宽屏顶部栏显示品牌、模型、工作区、Git 分支和连接状态；中窄宽度按设计隐藏次要字段。（验证：运行 120×36、80×24、60×18 Pilot 尺寸测试并比较 Header 可见字段）
- [ ] **AC3：** True Color 下呈现石墨黑、青蓝和洋红色板，256 色、基础色及 NO_COLOR 下仍可辨识。（验证：运行 `uv run pytest tests/test_tui_app.py tests/test_tui_widgets.py -q -k "color or no_color"` 并查看对应快照）
- [ ] **AC4：** 用户消息显示 `›`，MewCode 回复显示 `◆`，用户可见界面及纯文本输出均不出现 `assistant` 标签。（验证：`uv run pytest tests/test_tui_widgets.py tests/test_tui_plain.py -q -k "message or assistant"`；`! rg -n "╰─ assistant| assistant$" mewcode/tui README.md`）
- [ ] **AC20：** 品牌、状态、确认、错误和退出文案为英文，中文输入与中文 Markdown 回复显示正常。（验证：Pilot 输入中文并流式返回中文标题、列表和代码，断言内容完整）
- [ ] Unicode 不可用时使用 `>`、`*` 和 ASCII 边框，不出现替换字符。（验证：运行 `uv run pytest tests/test_tui_app.py tests/test_tui_plain.py -q -k ascii`）
- [ ] 静止界面不闪烁或持续刷新；只有活动状态的符号和耗时发生变化。（验证：分别在 READY 与 UPLINKING 状态采样两帧并比较变化区域）

## 流式状态与内容

- [ ] **AC5：** 首片段延迟时立即显示 `UPLINKING <model> · <elapsed>`，计时递增；首片段到达后同一位置转换为正文且无残留状态行。（验证：延迟假 Provider 的 Pilot 测试）
- [ ] **AC6：** 工具执行显示 `EXECUTING <tool>`，结果回灌等待显示 `SYNTHESIZING`，随后转换为最终正文。（验证：`uv run pytest tests/test_tui_app.py -q -k tool_turn`）
- [ ] **AC7：** 多个延迟片段在流结束前可见，完成后标题、列表、引用、表格、行内代码和代码块正确排版。（验证：`uv run pytest tests/test_tui_widgets.py -q -k markdown`）
- [ ] **AC8：** 普通正文自动换行；代码、diff 和命令输出保持列结构并可横向查看。（验证：在 80 列 Pilot 中渲染超长正文和代码，检查换行及横向滚动范围）
- [ ] **AC22：** 大量单字符片段无丢失、重复、乱序或明显卡顿，输入与缩放仍可响应。（验证：`uv run pytest tests/test_tui_app.py -q -k "rapid_chunks or batch"`，核对最终拼接文本）
- [ ] 首次文本事件不会被完整 Markdown 缓冲阻塞，片段在下一个可见刷新周期出现。（验证：在假 Provider 发出首片段后、完成信号前断言回复 Widget 已更新）
- [ ] 工具前言、工具卡和最终回复按时间顺序成为独立内容块，空前言不会产生空白回复卡。（验证：分别运行有前言和无前言工具回合测试）

## 滚动与响应式行为

- [ ] **AC9：** 位于底部时自动跟随；向上滚动后冻结位置并显示 `NEW OUTPUT ↓`；按 End 或触发提示后恢复跟随。（验证：`uv run pytest tests/test_tui_widgets.py -q -k scroll`）
- [ ] 用户冻结滚动后调整窗口尺寸，不会无故恢复自动跟随或跳到底部。（验证：Pilot 向上滚动、resize、追加片段并比较 scroll offset）
- [ ] **AC18：** 120×36、80×24、60×18 和运行中缩放时内容不重叠、草稿不丢失、滚动位置稳定。（验证：`uv run pytest tests/test_tui_app.py -q -k responsive`）
- [ ] 低于 48×14 时显示明确尺寸提示；恢复尺寸后原对话与草稿仍存在。（验证：Pilot 从 80×24 缩至 40×10，再恢复并断言状态）

## 输入、历史与退出

- [ ] **AC10：** 输入框从一行自动扩展到最多约六行，Enter 提交，Shift+Enter 或 Ctrl+J 换行，多行粘贴只产生一次提交。（验证：`uv run pytest tests/test_tui_widgets.py -q -k composer`）
- [ ] **AC11：** 生成期间可以编辑下一条草稿，但 Enter 不会排队或影响当前请求；回合结束后草稿保持可提交。（验证：`uv run pytest tests/test_tui_app.py -q -k draft`）
- [ ] **AC12：** 空输入框可用上下键浏览当前会话提示，回到末尾时恢复草稿；新应用实例没有旧历史。（验证：`uv run pytest tests/test_tui_widgets.py tests/test_tui_app.py -q -k history`）
- [ ] **AC13：** 生成期间按 Esc 或 Ctrl+C 后停止显示新片段，保留已有内容并标记 INTERRUPTED；后续模型上下文不包含残缺回复。（验证：`uv run pytest tests/test_tui_app.py tests/test_runtime.py -q -k "interrupt or cancel"`）
- [ ] **AC14：** 有输入时 Ctrl+C 清空；空闲空输入第一次 Ctrl+C 提示、2 秒内第二次退出；空输入 Ctrl+D、`exit` 和 `quit` 均退出。（验证：`uv run pytest tests/test_tui_app.py tests/test_tui_plain.py -q -k exit`）
- [ ] 中断后旧 Worker 的迟到片段、完成或错误事件不会改变新界面状态。（验证：发送带旧 generation id 的事件并断言被忽略）
- [ ] 应用退出时活动流被取消，未决确认被解析为拒绝，不残留后台 Worker。（验证：在等待 Provider 与确认弹层两种状态退出 Pilot）

## 工具、确认、错误与安全

- [ ] **AC15：** 工具卡显示工具名、脱敏关键参数、状态和耗时，结束时按 call id 原地更新，大段细节默认折叠。（验证：`uv run pytest tests/test_tui_interaction.py tests/test_tui_widgets.py -q -k tool`）
- [ ] 读取和搜索的完整工具结果不会进入展示事件或终端，只显示状态与截断元数据。（验证：用独特结果字符串执行假工具，断言只存在于模型反馈而不在 Pilot screen/plain output）
- [ ] **AC16：** 命令、写文件和改文件执行前显示聚焦确认弹层；默认焦点为拒绝，Esc/N 拒绝，Y 或显式按钮批准。（验证：`uv run pytest tests/test_tui_widgets.py tests/test_tui_interaction.py -q -k confirmation`）
- [ ] 拒绝确认不会产生文件或命令副作用，模型收到结构化拒绝结果。（验证：运行现有写文件拒绝端到端测试和新弹层拒绝测试）
- [ ] API key 不出现在顶部栏、工具卡、确认弹层、错误卡、快照或纯文本输出。（验证：使用唯一测试密钥运行相关测试，再对捕获输出和快照执行 `! rg -n "test-secret-api-key" tests/snapshots`）
- [ ] **AC17：** Provider、网络和工具错误在发生位置显示安全原因与建议，技术详情默认折叠；错误后仍可提交下一条消息。（验证：`uv run pytest tests/test_tui_app.py -q -k error`）
- [ ] Provider 部分失败时已显示文本保留，但残缺助手消息不进入历史。（验证：运行部分文本后抛错的 Runtime + Pilot 集成测试）
- [ ] 已开始的工具在用户中断后不会被描述为已回滚；工具安全返回后不再发起最终 Provider 请求。（验证：阻塞假工具的中断测试）

## 终端模式与兼容性

- [ ] **AC19：** 任意输入或输出非 TTY 时自动使用线性纯文本模式，不包含颜色、全屏、光标移动或动画控制序列。（验证：`uv run pytest tests/test_tui_mode.py tests/test_tui_plain.py -q`，并断言捕获输出不含 ESC 字节）
- [ ] 只有实际标准输入输出均为 TTY 时选择 FULLSCREEN；注入流、缺失 isatty、异常或重定向均选择 PLAIN。（验证：终端模式决策表测试全部通过）
- [ ] Git 分支正常显示；Git 缺失、非仓库、detached HEAD 和超时只隐藏字段，不阻止启动。（验证：`uv run pytest tests/test_tui_metadata.py -q`）
- [ ] 纯文本模式保留流式输出、工具确认、错误恢复、空输入忽略、exit、quit 和 EOF 行为。（验证：`uv run pytest tests/test_tui_plain.py -q`）
- [ ] Textual 内部组件不会被 Runtime、Provider 或工具模块导入。（验证：`! rg -n "mewcode\.tui|from .*tui|import .*tui" mewcode/runtime.py mewcode/providers mewcode/tools`）

## 集成与回归

- [ ] **AC21：** OpenAI 与 Anthropic 的普通回复、工具增量、历史序列化、thinking 保留和错误脱敏测试全部通过。（验证：`uv run pytest tests/test_providers.py -q`）
- [ ] **AC21：** 单工具执行、多个工具拒绝、参数解析失败、二次工具额度和结构化反馈语义保持不变。（验证：`uv run pytest tests/test_runtime.py tests/test_tool_executor.py -q`）
- [ ] **AC21：** 文件工具、命令工具、搜索工具和工作区逃逸防护全部回归通过。（验证：`uv run pytest tests/test_file_tools.py tests/test_command_tool.py tests/test_search_tools.py tests/test_workspace.py -q`）
- [ ] 取消前、活动流中和流退出后的关闭函数均只执行预期次数，不会关闭下一轮流。（验证：`uv run pytest tests/test_turns.py -q`）
- [ ] CLI 保持当前工作目录为工具工作区，配置错误返回非零状态，注入流走纯文本模式。（验证：`uv run pytest tests/test_cli.py -q`）
- [ ] 同一时间最多运行一个回合，忙碌状态不会启动第二个 Worker。（验证：快速连续提交两次，断言 Runtime 仅收到第一次）
- [ ] **AC23：** 所有全屏交互均可由假 Provider、假工具和 Textual Pilot 自动验证，无需真实网络或危险命令。（验证：断开网络运行 `uv run pytest tests/test_tui_app.py tests/test_tui_widgets.py -q`）

## 编译、测试与构建

- [ ] 依赖锁文件与项目声明一致。（验证：`uv lock --check && uv sync --all-groups`）
- [ ] 全部测试通过。（验证：`uv run pytest`）
- [ ] 所有生产代码和测试可编译。（验证：`uv run python -m compileall mewcode tests`）
- [ ] Wheel 构建成功并包含 `mewcode/tui/cyberpunk.tcss`。（验证：`uv build --wheel && unzip -l "$(ls -t dist/*.whl | head -n 1)" | rg "mewcode/tui/cyberpunk.tcss"`）
- [ ] 两个启动入口均可加载应用。（验证：分别运行 `uv run python -m mewcode` 和 `uv run mewcode`，观察相同启动界面或相同安全配置错误）
- [ ] 代码与文档 diff 无空白错误、编码替换字符、真实密钥或无关修改。（验证：`git diff --check`、`! LC_ALL=C rg -n $'\xEF\xBF\xBD' mewcode tests docs README.md`、`! rg -n "sk-[A-Za-z0-9]{20,}" mewcode tests docs README.md`、人工检查 `git diff --stat`）

## 端到端场景

- [ ] **场景 1——普通流式对话：** 在 80×24 TTY 启动，看到品牌卡；提交含 Markdown 的中文请求，先显示 UPLINKING，再以 `◆` 流式呈现格式化回复；完成后焦点回到保留草稿的输入框。（验证：Textual Pilot 端到端测试并保存实际屏幕证据）
- [ ] **场景 2——批准工具：** 模型请求写文件，界面显示 EXECUTING 和 diff 弹层；显式批准后只修改临时工作区目标文件，工具卡成功，随后显示 SYNTHESIZING 和最终答复。（验证：临时目录 E2E，比较执行前后文件及屏幕事件顺序）
- [ ] **场景 3——拒绝工具：** 模型请求命令或写文件，按 Esc 拒绝；无副作用，工具卡显示 rejected，模型收到拒绝反馈并生成最终说明。（验证：临时目录 E2E，断言文件/命令记录未变化）
- [ ] **场景 4——中断回复：** 在首片段前和部分回复后分别按 Esc；界面立即显示 INTERRUPTED，迟到片段被忽略，下一轮上下文没有残缺回复。（验证：可控阻塞 Provider E2E）
- [ ] **场景 5——错误后恢复：** Provider 在部分文本后失败；界面保留文本并显示错误卡，随后提交第二条消息成功获得回复。（验证：两回合假 Provider E2E）
- [ ] **场景 6——非 TTY：** 管道输入两条消息和 exit，捕获输出为无控制序列的线性记录，包含 `›`、`◆`，不包含 `assistant`。（验证：CLI 注入流 E2E 并检查原始字节）
- [ ] **场景 7——尺寸与颜色降级：** 对话过程中从宽屏缩至 too-small 再恢复，并切换 NO_COLOR/ASCII 能力；草稿与对话保持，所有状态仍可理解。（验证：Pilot resize 与能力注入 E2E）
