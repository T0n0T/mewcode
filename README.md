# MewCode

MewCode is a command-line AI chat assistant. This first version is intentionally small: it supports interactive multi-turn chat with streaming model output, but it does not perform tool use, file operations, code editing, shell execution, or repository indexing.

## Usage

Create a user-level config file:

```bash
mkdir -p ~/.mewcode
$EDITOR ~/.mewcode/config.yaml
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

MewCode reads one active provider config from:

```text
~/.mewcode/config.yaml
```

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
