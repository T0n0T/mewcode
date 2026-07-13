# MewCode

MewCode is a command-line AI chat assistant with interactive multi-turn chat, streaming model output, and a small workspace tool system.

## Tools and safety

MewCode exposes six tools to both supported providers:

- `read_file` reads UTF-8 text files.
- `write_file` creates or replaces UTF-8 text files after confirmation.
- `edit_file` performs one exact text replacement after confirmation.
- `run_command` runs a shell command after confirmation.
- `glob_files` finds workspace files by pattern.
- `search_code` searches text content by literal text or regular expression.

Each turn may execute at most one tool. After the result is returned, the model may only produce a final text answer; a second tool request is rejected.

File tools accept workspace-relative paths only and prevent `..`, absolute-path, and symlink escapes. Explicit `read_file` paths may read ignored files, while `glob_files` and `search_code` follow `.gitignore` and always exclude `.git`. File content must be valid UTF-8 text.

`write_file`, `edit_file`, and `run_command` require confirmation every time. Only `y` or `yes` approves an action. Shell commands run from the startup directory with the current shell's semantics. They do not run in an operating-system-level sandbox and can affect anything permitted to the MewCode process; review every command before approving it.

## Usage

Create a config file. MewCode first checks the current working directory, then
falls back to the user-level config:

```bash
mkdir -p .mewcode
$EDITOR .mewcode/config.yaml
```

Start MewCode:

```bash
uv run mewcode
```

You can also run the module directly:

```bash
uv run python -m mewcode
```

Exit the session with `exit`, `quit`, or Ctrl-D.

## Configuration

MewCode reads one active provider config. Lookup order:

```text
./.mewcode/config.yaml
~/.mewcode/config.yaml
```

The project-local file wins when both exist.

The supported fields are:

```yaml
name: openai-main
protocol: openai
model: gpt-5-mini
base_url: https://api.openai.com/v1
api_key: your-api-key
thinking: false
```

Anthropic example:

```yaml
name: claude-main
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: your-api-key
thinking: true
```

`thinking` is optional and defaults to `false`. When Anthropic thinking is enabled, MewCode requests adaptive extended thinking with omitted thinking display, so only the final answer appears in the terminal.

Do not commit real API keys to the repository.
