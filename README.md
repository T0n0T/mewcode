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

### Terminal interface

When standard input and output are both real TTYs, MewCode opens a full-screen,
keyboard-first interface with a session header, scrollable conversation, and
persistent multiline composer. Piped input, redirected output, and injected
test streams automatically use plain linear output without color, animation,
or full-screen control sequences.

Fullscreen controls:

- `Enter` submits the current prompt.
- `Shift+Enter` or `Ctrl+J` inserts a newline. The composer grows to six lines.
- `Esc` interrupts an active response. Inside a confirmation dialog, it rejects
  the operation instead.
- `Ctrl+C` interrupts an active response, clears a non-empty idle draft, or
  arms exit when the idle composer is empty; press it again within two seconds
  to exit.
- `Ctrl+D` exits when the idle composer is empty.
- `End` returns a conversation paused by upward scrolling to the latest output.
- `exit` and `quit` also end the session.

You may edit the next draft while a response is streaming, but `Enter` does not
queue or steer another request. Up and Down browse prompts submitted during the
current session when the composer is empty. Drafts, prompt history, and
conversation state are not restored after restart.

Set `NO_COLOR=1` to keep the full-screen hierarchy while removing color. MewCode
also falls back to ASCII markers when the output encoding cannot represent its
Unicode symbols.

This version has no slash commands, command palette, model switcher, theme
configuration, or persistent chat history.

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
