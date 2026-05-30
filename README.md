# Civil Engineering Design Assistant

An MCP server that gives civil engineers working in AutoCAD a knowledgeable co-pilot inside Claude Desktop, Claude Code, or Cursor.

## Quick start

```bash
# Install
uv sync

# Phase 0: Download York Region guidelines
civil-eng-agent scrape

# Phase 1: Ingest into corpus.db
civil-eng-agent ingest

# Start the MCP server
civil-eng-agent-serve
```

## MCP client config

Add to your Claude Desktop / Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "civil-eng-agent": {
      "command": "uv",
      "args": ["run", "civil-eng-agent-serve"],
      "cwd": "/absolute/path/to/civil-eng-agent"
    }
  }
}
```

## Development

```bash
uv sync --extra dev
uv run pytest tests/
uv run python eval/harness.py
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full design documentation.
