# MewCode

MewCode is a command-line AI chat assistant with interactive multi-turn chat,
streaming model output, an autonomous Agent Loop, and a small workspace tool
system.

## Agent Loop

Each request can continue through multiple model and tool rounds without the
user sending “continue.” MewCode streams model text as it arrives, waits for a
complete response before executing any collected calls, runs the permitted tool
batches, feeds their structured results back to the model, and repeats until the
model returns a complete response without tools.

Every run reports its mode, current round, progress, tool state, Provider token
usage when available, and a machine-readable stop reason. A run stops when:

- the model naturally completes without another tool call;
- the tenth iteration finishes, without an eleventh request or extra summary;
- the user cancels the active model, tool, or confirmation wait;
- three consecutive rounds contain only unknown tools; or
- the Provider connection, stream parsing, or completion protocol fails.

Complete assistant calls and their tool results are committed to the in-process
history as one unit. A cancelled or broken partial iteration is not committed,
while complete earlier iterations remain available to the next request.

### Plan mode

- `/plan <task>` runs the same Agent Loop with only `read_file`, `glob_files`,
  and `search_code` visible, then saves a naturally completed answer as the
  current plan.
- `/do` executes the most recent saved and not-yet-completed plan with all six
  tools. It accepts no extra task text.
- A successful new `/plan` replaces the previous plan. Cancellation, Provider
  errors, the iteration limit, or repeated unknown tools preserve the previous
  plan.
- A naturally completed `/do` marks the plan complete. An interrupted or failed
  `/do` leaves it ready to retry; a completed plan cannot be executed twice.

Plans, history, progress, events, and usage remain in memory only and are not
persisted after restart.

## Tools and safety

MewCode exposes six tools to both supported providers:

- `read_file` reads UTF-8 text files.
- `write_file` creates or replaces UTF-8 text files after confirmation.
- `edit_file` performs one exact text replacement after confirmation.
- `run_command` runs a shell command after confirmation.
- `glob_files` finds workspace files by pattern.
- `search_code` searches text content by literal text or regular expression.

One model response may request multiple tools. Adjacent read, glob, and search
calls can run concurrently. Write, edit, and command calls run serially and act
as ordering barriers; model feedback always preserves the original call order.
Unknown tools, invalid arguments, rejection, timeout, and ordinary tool failures
become structured feedback so the model can adjust within the remaining rounds.

File tools accept workspace-relative paths only and prevent `..`, absolute-path, and symlink escapes. Explicit `read_file` paths may read ignored files, while `glob_files` and `search_code` follow `.gitignore` and always exclude `.git`. File content must be valid UTF-8 text.

`write_file`, `edit_file`, and `run_command` require confirmation every time,
including during `/do`; there is no automatic approval or permission system.
Only `y` or `yes` approves an action in the plain interface. Shell commands run
from the startup directory with the current shell's semantics. They do not run
in an operating-system-level sandbox and can affect anything permitted to the
MewCode process; review every command before approving it. Cancellation does
not promise to roll back a side effect that already started.

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
keyboard-first interface with a scrollable conversation, persistent multiline
composer, and compact session footer below it. On normal terminal sizes, a
one-cell safe margin keeps the interface away from every terminal edge. Piped
input, redirected output, and injected test streams automatically use plain
linear output without color, animation, or full-screen control sequences.

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

This version has `/plan` and `/do`, but no command palette, model switcher,
theme configuration, context compression, persistent chat history or plans,
checkpoint recovery, multi-agent delegation, or configurable permission
system.

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
