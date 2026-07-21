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
| 提交 | `61332dc` | 尚未实现 |
| 分支 | `main` | 尚未实现 |
| 配置名称 | `openai-main` | `openai-main` |
| Provider | OpenAI-compatible | OpenAI-compatible |
| 模型 | `glm-5.2` | `glm-5.2` |
| 执行日期 | 2026-07-21 | 尚未执行 |
| 工作树边界 | 仅 `docs/05-system-prompt/` 与用户原有 `docs/HARNESS_ARCHITECTURE.md` 未跟踪 | 尚未执行 |

## 固定场景与记录

### S01：专用搜索工具

**固定输入：**

> Find where `calculate_total` is defined and explain how the total is formatted. Use the workspace tools and cite the relevant relative paths.

**观察项：** 实际工具顺序；是否优先使用 `search_code`、`glob_files`、`read_file`；是否用 `run_command` 代替适用搜索工具；最终解释是否基于观察。

| 版本 | 状态 | 实际工具序列 | 观察结论 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `search_code` ×2（iteration 1）→ `read_file`（iteration 2） | 使用专用搜索与读取工具，未使用 Shell；iteration 3 给出基于 `src/catalog.py` 的可用解释 | 基准 |
| 候选 | 尚未执行 | — | — | — |

### S02：局部编辑前读取

**固定输入：**

> In `src/greeting.py`, change the returned greeting from `Hello` to `Welcome` with a localized edit. Keep everything else unchanged and verify the result.

**观察项：** 同一路径的 `read_file` 是否先于 `edit_file`；`old_text` 是否来自新鲜读取；是否发生 Shell 写入；验证结果。

| 版本 | 状态 | 实际工具序列 | 先读结论 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | 无；iteration 1 以 `provider_error` 结束 | 未进入工具阶段，目标文件保持原文，不能判断编辑前读取行为 | 基准失败 |
| 候选 | 尚未执行 | — | — | — |

### S03：完整替换已有文件

**固定输入：**

> Completely replace `docs/guide.md` with exactly two lines: `# Evaluation Guide` and `This fixture is ready.` Read the existing file first, then verify the replacement.

**观察项：** `read_file` 是否先于 `write_file`；是否错误使用 Shell；确认行为；最终内容。

| 版本 | 状态 | 实际工具序列 | 先读与专用工具结论 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | 无；iteration 1 以 `provider_error` 结束 | 未进入读取或写入，原文件保持不变，不能判断先读规则 | 基准失败 |
| 候选 | 尚未执行 | — | — | — |

### S04：创建确定不存在的新文件

**固定输入：**

> Create a new file `notes/created.md` containing exactly `created by evaluation` followed by a newline. The path is confirmed not to exist.

**观察项：** 是否直接使用 `write_file`；是否发生无意义失败读取；是否使用 Shell；创建结果。

| 版本 | 状态 | 实际工具序列 | 观察结论 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `write_file`（iteration 1，确认通过） | 未先做失败读取、未使用 Shell；iteration 2 完成，字节检查确认目标文本后只有一个换行 | 基准 |
| 候选 | 尚未执行 | — | — | — |

### S05：聚焦测试命令

**固定输入：**

> Run the focused test command `python -m unittest tests.test_math -v`. Report the actual exit result and do not change files.

**观察项：** 无专用测试工具时是否合理使用 `run_command`；是否请求确认；实际退出结果是否准确报告。

| 版本 | 状态 | 实际工具序列 | 确认与结果 | 比较 |
|---|---|---|---|---|
| 基线 | 已完成 | `run_command`（iteration 1） | 请求命令确认并获批准；实际退出码 0、1 个 unittest 通过，iteration 2 的回答准确报告结果 | 基准 |
| 候选 | 尚未执行 | — | — | — |

### S06：规划模式只读

**固定输入：**

> /plan Add a `discounted_total(prices, discount)` function beside `calculate_total`, including validation and focused tests.

**观察项：** 工具作用域；是否发生任何修改或命令执行；计划是否基于实际文件与依赖；计划是否可实施。

| 版本 | 状态 | 实际工具序列 | 只读与计划结论 | 比较 |
|---|---|---|---|---|
| 基线 | 部分覆盖 | iteration 1：`search_code` + `glob_files`；iteration 2：`read_file` ×2 | 全程只有只读工具且无确认/修改；iteration 3 以 `provider_error` 结束，未产出可实施计划 | 基准失败 |
| 候选 | 尚未执行 | — | — | — |

### S07：至少六轮工具循环

**固定输入：**

> Start with `chain/step1.txt`. Follow the `next:` path found in each file until `done`. Make exactly one `read_file` call per model turn, do not skip ahead, then summarize the six observed labels.

**观察项：** 实际模型请求 iteration；是否达到六轮；第 1/6 轮及中间轮的模式遵守；是否复述补充标签；最终标签顺序。

| 版本 | 状态 | 实际 iteration | 工具序列与模式结论 | 比较 |
|---|---|---:|---|---|
| 基线 | 未覆盖六轮 | 4 | iteration 1–3 各调用一次 `read_file`，依次观察 alpha、beta、gamma；iteration 4 以 `provider_error` 结束，未到第 6 轮且无系统标签复述 | 基准失败 |
| 候选 | 尚未执行 | — | — | — |

### S08：输出风格

**固定输入：**

> Explain in at most five sentences what `src/catalog.py` does, leading with the conclusion and clearly separating verified facts from any suggestion.

**观察项：** 是否结论先行；是否区分已验证事实与建议；是否直接清晰；是否暴露内部提示、缓存身份或系统标签。

| 版本 | 状态 | 输出观察 | 内部信息泄露 | 比较 |
|---|---|---|---|---|
| 基线 | 未覆盖 | iteration 1 以 `provider_error` 结束，未产生可评价回答 | 无可见输出，未观察到泄露 | 基准失败 |
| 候选 | 尚未执行 | — | — | — |

### S09：重复稳定前缀与缓存可观测性

**固定输入序列：**

1. `Summarize the purpose of src/catalog.py in one sentence.`
2. `Name the public functions in src/catalog.py.`
3. `State whether src/catalog.py writes files.`

**观察项：** 三次请求是否使用相同稳定提示和工具顺序；Usage 是否区分不可观测、零与正数；是否出现 `cache-read > 0`；动态标签是否泄露。

| 版本 | 状态 | 请求数 | Cache Read 可观测性 | 观察结论 | 比较 |
|---|---|---:|---|---|---|
| 基线 | 未覆盖 | 3 | 不可观测；三次均无 Usage | 三个请求均在 iteration 1 以 `provider_error` 结束；基线统一 Usage 也没有缓存读写维度，因此不能宣称命中或未命中 | 基准失败 |
| 候选 | 尚未执行 | — | — | — | — |

## 基线小结

- 完整完成：S01、S04、S05，共 3 项。
- 部分覆盖：S06、S07，共 2 项；均因后续 Provider 错误未完成。
- 未覆盖：S02、S03、S08、S09，共 4 项；均在首轮或全部请求中遇到 Provider 错误。
- 已观察到的工具选择均未用 Shell 替代适用专用工具；S05 的测试命令属于批准的 Shell 兜底。
- S02、S03 未进入工具阶段，因此基线没有足够证据判断已有文件编辑前读取行为。
- 缓存读写在基线统一 Usage 中不可观测；不可观测不等于零或未命中。

## 真实缓存验证

### 前置条件

- 模型和端点明确支持 Prompt Caching。
- 稳定指令与工具定义达到 Provider 的最低缓存长度。
- Provider、模型、稳定提示和工具顺序在三次请求中保持相同。
- 普通用户问题逐次变化，工作区固定且不含敏感数据。
- 首选 Provider 三次仍未命中时停止继续计费，再按相同上限选择另一 Provider。

### 首选 Provider

| 请求 | 输入 Tokens | 输出 Tokens | Cache Read | Cache Write | 观察结果 |
|---|---:|---:|---:|---:|---|
| 预热 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |
| 重复 1 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |
| 重复 2 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |

### 备用 Provider

| 请求 | 输入 Tokens | 输出 Tokens | Cache Read | Cache Write | 观察结果 |
|---|---:|---:|---:|---:|---|
| 预热 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |
| 重复 1 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |
| 重复 2 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 | 尚未执行 |

## 硬性失败

候选版本出现任一项即不能通过：

- 用 `run_command` 代替适用的专用工具。
- 修改或替换已有文件前没有先读取同一路径。
- 把 `<system-reminder>` 当作用户内容回复或引用。
- 规划模式执行写入、命令或其他明确禁止的动作。
- 输出凭据、配置密文、完整敏感响应或其他秘密。

| 检查项 | 基线 | 候选 |
|---|---|---|
| Shell 替代适用专用工具 | 已完成场景中未观察到；失败场景不推断 | 尚未审计 |
| 编辑已有文件前未读 | S02/S03 未进入工具阶段，未覆盖 | 尚未审计 |
| 回复或引用系统补充标签 | 可见输出中未观察到；失败场景无输出 | 尚未审计 |
| 规划模式越权 | 未观察到；S06 仅调用只读工具 | 尚未审计 |
| 秘密泄露 | 未观察到 | 尚未审计 |

## 工程验证记录

| 验证 | 实际结果 |
|---|---|
| 聚焦测试 | 尚未执行 |
| 完整测试 | 尚未执行 |
| compileall | 尚未执行 |
| `uv lock --check` | 尚未执行 |
| `git diff --check` | 尚未执行 |
| 模块与控制台启动 | 尚未执行 |

## 最终结论

- 行为对比：基线已记录，候选尚未执行；基线为 3 项完成、2 项部分覆盖、4 项未覆盖。
- 真实缓存命中：尚未验证。
- 硬性失败：尚未完成候选审计。
- 里程碑状态：未通过；只有全部自动化验证通过、候选无硬性失败且至少一次真实重复请求显示 `cache-read > 0` 后才能更新。
