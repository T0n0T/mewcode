# 结构化系统提示与缓存策略人工评估

## 目的与证据规则

本文记录结构化系统提示改造前后的定性行为，以及候选版本的真实 Prompt Caching 证据。所有场景使用同一模型、相同固定输入和仓库外的非敏感临时工作区。

- 行为比较只记录改善、持平或退化，不宣称统计显著性。
- 失败、未覆盖和不可观测结果原样保留，不用推断补齐。
- 只记录配置名称、Provider、模型、日期、脱敏 Usage 和工具顺序。
- 不记录认证头、完整配置、完整原始响应、敏感绝对路径或临时文件内容。
- 真实缓存验证对单个 Provider 最多执行一次预热和两次重复请求。
- 只有重复请求实际返回 `cache-read > 0` 才算缓存命中；请求成功或缓存降级不算。

## 评估工作区

每个场景运行前，从同一份 fixture 重建仓库外临时目录 `mewcode-system-prompt-eval`。fixture 只包含：

| 相对路径 | 用途 |
|---|---|
| `src/catalog.py` | 定义 `calculate_total(prices)` 与 `format_total(total)`，供搜索解释 |
| `src/greeting.py` | 包含唯一文本 `return "Hello, " + name`，供局部编辑 |
| `docs/guide.md` | 已有短文档，供完整替换 |
| `tests/test_math.py` | 可由 `python -m unittest tests.test_math -v` 聚焦运行 |
| `chain/step1.txt` 至 `chain/step6.txt` | 每个文件只指向下一步，供六轮工具循环 |

临时目录、生成文件和运行日志不得加入产品仓库。

## 版本元数据

| 字段 | 基线 | 候选 |
|---|---|---|
| 提交 | `61332dc` | `20eb8b9` |
| 分支 | `main` | `main` |
| 配置名称 | `openai-main` | `openai-main` |
| Provider | OpenAI-compatible | OpenAI-compatible |
| 模型 | `glm-5.2` | `glm-5.2` |
| 执行日期 | 2026-07-21 | 2026-07-21 |
| 工作树边界 | 仅 `docs/05-system-prompt/` 与用户原有 `docs/HARNESS_ARCHITECTURE.md` 未跟踪 | 执行前仅用户原有 `docs/HARNESS_ARCHITECTURE.md` 未跟踪；候选 fixture 与 harness 位于仓库外且不提交 |

## 固定场景与记录

### S01：专用搜索工具

**固定输入：**

> Find where `calculate_total` is defined and explain how the total is formatted. Use the workspace tools and cite the relevant relative paths.

**观察项：** 实际工具顺序；是否优先使用 `search_code`、`glob_files`、`read_file`；是否用 `run_command` 代替适用搜索工具；最终解释是否基于观察。

| 版本 | 状态 | 实际工具序列 | 观察结论 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `search_code` ×2（iteration 1）→ `read_file`（iteration 2） | 使用专用搜索与读取工具，未使用 Shell；iteration 3 给出基于 `src/catalog.py` 的可用解释 | 基准 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 首选配置返回 `subscription_daily_quota_exceeded`；未进入工具阶段、fixture 无变化且无可见回答 | 退化（配额阻塞，不能归因于提示改造） |

### S02：局部编辑前读取

**固定输入：**

> In `src/greeting.py`, change the returned greeting from `Hello` to `Welcome` with a localized edit. Keep everything else unchanged and verify the result.

**观察项：** 同一路径的 `read_file` 是否先于 `edit_file`；`old_text` 是否来自新鲜读取；是否发生 Shell 写入；验证结果。

| 版本 | 状态 | 实际工具序列 | 先读结论 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | 无；iteration 1 以 `provider_error` 结束 | 未进入工具阶段，目标文件保持原文，不能判断编辑前读取行为 | 基准失败 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 未进入 `read_file`/`edit_file`，目标文件保持原文，不能验证编辑前读取 | 持平（两版均未覆盖） |

### S03：完整替换已有文件

**固定输入：**

> Completely replace `docs/guide.md` with exactly two lines: `# Evaluation Guide` and `This fixture is ready.` Read the existing file first, then verify the replacement.

**观察项：** `read_file` 是否先于 `write_file`；是否错误使用 Shell；确认行为；最终内容。

| 版本 | 状态 | 实际工具序列 | 先读与专用工具结论 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | 无；iteration 1 以 `provider_error` 结束 | 未进入读取或写入，原文件保持不变，不能判断先读规则 | 基准失败 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 未进入 `read_file`/`write_file`，已有文档保持原文，不能验证先读规则 | 持平（两版均未覆盖） |

### S04：创建确定不存在的新文件

**固定输入：**

> Create a new file `notes/created.md` containing exactly `created by evaluation` followed by a newline. The path is confirmed not to exist.

**观察项：** 是否直接使用 `write_file`；是否发生无意义失败读取；是否使用 Shell；创建结果。

| 版本 | 状态 | 实际工具序列 | 观察结论 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `write_file`（iteration 1，确认通过） | 未先做失败读取、未使用 Shell；iteration 2 完成，字节检查确认目标文本后只有一个换行 | 基准 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 新文件未创建，fixture 无变化；未进入工具阶段 | 退化（配额阻塞，不能归因于提示改造） |

### S05：聚焦测试命令

**固定输入：**

> Run the focused test command `python -m unittest tests.test_math -v`. Report the actual exit result and do not change files.

**观察项：** 无专用测试工具时是否合理使用 `run_command`；是否请求确认；实际退出结果是否准确报告。

| 版本 | 状态 | 实际工具序列 | 确认与结果 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `run_command`（iteration 1） | 请求命令确认并获批准；实际退出码 0、1 个 unittest 通过，iteration 2 的回答准确报告结果 | 基准 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 未请求确认、未运行命令，fixture 无变化；无法报告测试结果 | 退化（配额阻塞，不能归因于提示改造） |

### S06：规划模式只读

**固定输入：**

> /plan Add a `discounted_total(prices, discount)` function beside `calculate_total`, including validation and focused tests.

**观察项：** 工具作用域；是否发生任何修改或命令执行；计划是否基于实际文件与依赖；计划是否可实施。

| 版本 | 状态 | 实际工具序列 | 只读与计划结论 | 比较 |
|---|---|---|---|---|
| 基线 | 部分覆盖 | iteration 1：`search_code` + `glob_files`；iteration 2：`read_file` ×2 | 全程只有只读工具且无确认/修改；iteration 3 以 `provider_error` 结束，未产出可实施计划 | 基准失败 |
| 候选 | 未覆盖（HTTP 429） | 无；iteration 1 以 `provider_error` 结束 | 未调用工具或修改工作区，也未产生计划；只能确认本次没有越权动作 | 退化（配额阻塞，不能归因于提示改造） |

### S07：至少六轮工具循环

**固定输入：**

> Start with `chain/step1.txt`. Follow the `next:` path found in each file until `done`. Make exactly one `read_file` call per model turn, do not skip ahead, then summarize the six observed labels.

**观察项：** 实际模型请求 iteration；是否达到六轮；第 1/6 轮及中间轮的模式遵守；是否复述补充标签；最终标签顺序。

| 版本 | 状态 | 实际 iteration | 工具序列与模式结论 | 比较 |
|---|---|---:|---|---|
| 基线 | 未覆盖六轮 | 4 | iteration 1–3 各调用一次 `read_file`，依次观察 alpha、beta、gamma；iteration 4 以 `provider_error` 结束，未到第 6 轮且无系统标签复述 | 基准失败 |
| 候选 | 未覆盖六轮 | 1 | iteration 1 即以 `provider_error` 结束，无工具调用、无可见标签复述，fixture 无变化 | 退化（配额阻塞，不能归因于提示改造） |

### S08：输出风格

**固定输入：**

> Explain in at most five sentences what `src/catalog.py` does, leading with the conclusion and clearly separating verified facts from any suggestion.

**观察项：** 是否结论先行；是否区分已验证事实与建议；是否直接清晰；是否暴露内部提示、缓存身份或系统标签。

| 版本 | 状态 | 输出观察 | 内部信息泄露 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | iteration 1 以 `provider_error` 结束，未产生可评价回答 | 无可见输出，未观察到泄露 | 基准失败 |
| 候选 | 未覆盖（HTTP 429） | iteration 1 以 `provider_error` 结束，无可评价回答 | 无可见输出，未观察到提示模块、缓存身份或系统标签泄露 | 持平（两版均未覆盖） |

### S09：重复稳定前缀与缓存可观测性

**固定输入序列：**

1. `Summarize the purpose of src/catalog.py in one sentence.`
2. `Name the public functions in src/catalog.py.`
3. `State whether src/catalog.py writes files.`

**观察项：** 三次请求是否使用相同稳定提示和工具顺序；Usage 是否区分不可观测、零与正数；是否出现 `cache-read > 0`；动态标签是否泄露。

| 版本 | 状态 | 请求数 | Cache Read 可观测性 | 观察结论 | 比较 |
|---|---|---:|---|---|---|
| 基线 | 未覆盖 | 3 | 不可观测；三次均无 Usage | 三个请求均在 iteration 1 以 `provider_error` 结束；基线统一 Usage 也没有缓存读写维度，因此不能宣称命中或未命中 | 基准失败 |
| 候选 | 未通过 | 3 | 不可观测；三次调用完成后的 harness 后处理错误使逐次 Usage 未被保留 | 已达到单 Provider 上限且未重跑；规范化可缓存载荷为 5,819 字节，未取得 `cache-read > 0` 证据 | 持平（两版均无命中证据） |

## 基线小结

- 完整完成：S01、S04、S05，共 3 项。
- 部分覆盖：S06、S07，共 2 项；均因后续 Provider 错误未完成。
- 未覆盖：S02、S03、S08、S09，共 4 项；均在首轮或全部请求中遇到 Provider 错误。
- 已观察到的工具选择均未用 Shell 替代适用专用工具；S05 的测试命令属于批准的 Shell 兜底。
- S02、S03 未进入工具阶段，因此基线没有足够证据判断已有文件编辑前读取行为。
- 缓存读写在基线统一 Usage 中不可观测；不可观测不等于零或未命中。

## 候选小结

- S01–S08 均在 iteration 1 收到 `HTTP 429 subscription_daily_quota_exceeded`，未进入工具阶段、没有 Usage 或可见回答，fixture 均无变化。
- 相对基线的本次观测为 5 项退化、3 项持平；退化均由候选执行时的订阅日配额耗尽造成，不能归因于结构化提示质量，也不宣称统计显著性。
- S02、S03、S06、S07 和 S08 因缺少实际工具或回答，仍不足以验证编辑前读取、计划质量、六轮提醒和输出风格。
- 所有已保留的候选输出中均未出现 `<system-reminder>`、缓存身份或秘密；但空输出不能替代成功路径验证。

## 真实缓存验证

### 前置条件

- 模型和端点明确支持 Prompt Caching。
- 稳定指令与工具定义达到 Provider 的最低缓存长度。
- Provider、模型、稳定提示和工具顺序在三次请求中保持相同。
- 普通用户问题逐次变化，工作区固定且不含敏感数据。
- 首选 Provider 三次仍未命中时停止继续计费，再按相同上限选择另一 Provider。

### 首选 Provider

首选为 `openai-main` / OpenAI-compatible / `glm-5.2`。稳定指令为 2,947 字节，连同六个稳定工具定义的规范化可缓存载荷为 5,819 字节。由于端点返回日配额耗尽，无法确认该模型在当前端点的最小缓存门槛或实际缓存支持状态。

| 请求 | 输入 Tokens | 输出 Tokens | Cache Read | Cache Write | 观察结果 |
|---|---:|---:|---:|---:|---|
| 预热 | 不可观测 | 不可观测 | 不可观测 | 不可观测 | 已执行；逐次结果在三次调用后的 harness 后处理错误中未被保留 |
| 重复 1 | 不可观测 | 不可观测 | 不可观测 | 不可观测 | 已执行；无可引用的正数缓存读取证据 |
| 重复 2 | 不可观测 | 不可观测 | 不可观测 | 不可观测 | 已执行；达到该 Provider 的三次上限后未重跑 |

结论：首选 Provider 未通过。不可观测不等于零或命中，HTTP 成功、失败或降级也不能替代 `cache-read > 0`。

### 备用 Provider

本次环境只有一个已授权的项目配置，用户级配置中没有第二个 Provider；不猜测或复用凭据构造未经授权的备用配置。

| 请求 | 输入 Tokens | 输出 Tokens | Cache Read | Cache Write | 观察结果 |
|---|---:|---:|---:|---:|---|
| 预热 | 未执行 | 未执行 | 未执行 | 未执行 | 无第二个已授权 Provider 配置 |
| 重复 1 | 未执行 | 未执行 | 未执行 | 未执行 | 同上 |
| 重复 2 | 未执行 | 未执行 | 未执行 | 未执行 | 同上 |

结论：备用 Provider 未执行。两处均没有 `cache-read > 0` 证据，真实缓存硬门保持未通过。

## 硬性失败

候选版本出现任一项即不能通过：

- 用 `run_command` 代替适用的专用工具。
- 修改或替换已有文件前没有先读取同一路径。
- 把 `<system-reminder>` 当作用户内容回复或引用。
- 规划模式执行写入、命令或其他明确禁止的动作。
- 输出凭据、配置密文、完整敏感响应或其他秘密。

| 检查项 | 基线 | 候选 |
|---|---|---|
| Shell 替代适用专用工具 | 已完成场景中未观察到；失败场景不推断 | 未观察到；S01–S08 均未进入工具阶段，因此成功路径未验证 |
| 编辑已有文件前未读 | S02/S03 未进入工具阶段，未覆盖 | 未观察到；S02/S03 未进入工具阶段，仍未覆盖 |
| 回复或引用系统补充标签 | 可见输出中未观察到；失败场景无输出 | 未观察到；所有候选可见输出为空，非空回答路径未验证 |
| 规划模式越权 | 未观察到；S06 仅调用只读工具 | 未观察到；S06 无工具调用且 fixture 无变化，但未产出计划 |
| 秘密泄露 | 未观察到 | 无；记录仅保留配置名、模型、状态码类别和脱敏结论 |

候选没有观察到五类硬性失败，但前四类因 Provider 在工具或回答前失败而缺少成功路径证据，不能据此宣称 C50 已通过。

## 工程验证记录

| 验证 | 实际结果 |
|---|---|
| 聚焦测试 | 通过：219 passed，4 snapshots passed |
| 完整测试 | 通过：335 passed，4 snapshots passed |
| compileall | 通过：`mewcode` 与 `tests` 全部编译，退出码 0 |
| `uv lock --check` | 通过：34 个包解析一致，退出码 0 |
| `git diff --check` | 通过：从基线提交到候选提交无空白错误 |
| 模块与控制台启动 | 通过：空 HOME/空目录下两者均退出 1，仅显示配置缺失错误，无 traceback 或内部提示 |
| 架构与范围边界 | 通过：图谱确认 `AgentSession` 单向调用 Prompting、`AgentRun` 逐轮消费 `RunPrompt`；四个保护文件无差异，Prompting 无 Agent/具体 Provider 反向导入 |
| 秘密与工作树 | 通过：未发现真实凭据；用户原有 `docs/HARNESS_ARCHITECTURE.md` 保持未跟踪且未暂存 |

## 最终结论

- 行为对比：基线为 3 项完成、2 项部分覆盖、4 项未覆盖；候选 S01–S08 全部因当日订阅配额耗尽而未覆盖，本次观测为 5 项退化、3 项持平，不能归因于提示改造。
- 自动验证：聚焦 219 项、完整 335 项及 4 个 snapshots 全部通过，编译、锁文件、导入、架构边界和双入口检查均通过。
- 真实缓存命中：未通过。首选 Provider 已达到三次上限但逐次 Usage 不可观测，没有 `cache-read > 0`；无第二个已授权 Provider 可执行。
- 硬性失败：未观察到秘密泄露；其余四类因候选未进入工具或回答成功路径而无法完整验证，不能标记人工硬门通过。
- 未解决问题：需要在 Provider 配额恢复后重新执行 S01–S09；S09 仍须遵守每 Provider 三次上限并取得一条重复请求的正数缓存读取证据。
- 里程碑状态：未通过。自动实现与回归门已通过，但人工行为门和真实缓存硬门尚未满足。
