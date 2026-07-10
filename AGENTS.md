# AGENTS.md

## 项目说明

- MewCode 是一个 Python 3.13 CLI 聊天助手。
- 第一版聚焦交互式对话、流式输出和 Provider 抽象。
- 除非 spec 明确变更，不要加入 tool use、文件编辑、shell 执行、仓库索引或对话历史持久化。

## 规格流程

- 新增功能、配置变更、模块变更或较大的文档结构调整前，先使用 `mew-spec`。
- 每个里程碑使用独立目录 `docs/<序号>-<名称>/`，保留该阶段完整的规格与设计记录。
- 每个里程碑目录内按 `spec.md`、`plan.md`、`task.md`、`checklist.md` 的顺序推进；开始工作前先确认当前里程碑目录。
- 实现前应确保相关需求、设计、任务和验收点已经写清楚；小改动也要同步已有文档中的对应描述。
- 当前请求若只是修正文案、翻译或补充说明，可以直接改文档，但仍要保持与既有 spec/plan/task/checklist 一致。

## 配置

- 默认配置查找顺序：
  1. `./.mewcode/config.yaml`
  2. `~/.mewcode/config.yaml`
- 两者同时存在时，项目级配置优先生效。
- 不要提交真实 API key；示例配置使用 `config.yaml.example`。

## 验证

- 窄范围改动运行聚焦测试，例如 `uv run pytest tests/test_config.py`。
- 较大改动交付前运行 `uv run pytest`。
- 修改导入、入口或包结构时运行 `uv run python -m compileall mewcode tests`。

## 编辑约定

- 改动保持小而清晰，并贴合现有模块结构。
- 保留用户已有改动，不要回滚无关的脏工作区内容。
- 错误信息要清楚，并避免泄露 `api_key`。
