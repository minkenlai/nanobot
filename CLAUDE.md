# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all tests
pytest
# or
uv run pytest tests/

# Run a single test file
pytest tests/agent/test_memory_consolidation_types.py

# Lint
ruff check nanobot/

# Format
ruff format nanobot/
```

## Architecture

**nanobot** is an ultra-lightweight AI agent framework (~2,000 lines of core agent code). It receives messages from chat platforms, processes them through an LLM with tool execution, and streams responses back.

### Message Flow

```
Chat Channel → MessageBus → AgentLoop → LLMProvider → ToolRegistry → MessageBus → Chat Channel
```

`AgentLoop` (`nanobot/agent/loop.py`) is the core orchestrator. After each turn, `MemoryConsolidator` summarizes to `MEMORY.md` / `HISTORY.md` in the agent's workspace.

### Key Packages

| Package | Role |
|---------|------|
| `nanobot/agent/` | Core agent: loop, context building, memory, tools, subagents |
| `nanobot/providers/` | LLM backends (Anthropic, OpenAI-compat, Azure, OAuth) |
| `nanobot/channels/` | Chat platform integrations (12 platforms) |
| `nanobot/bus/` | Async message queue between channels and agent |
| `nanobot/session/` | Per-conversation history (JSONL append-only) |
| `nanobot/config/` | Pydantic config schema + workspace path resolution |
| `nanobot/cli/` | Typer CLI (`agent`, `gateway`, `onboard`, `status`, etc.) |
| `nanobot/skills/` | Bundled skills loaded from `~/.nanobot/workspace/skills/` |

### Provider System

`nanobot/providers/registry.py` is the single source of truth for 25+ providers. Each `ProviderSpec` defines name, keywords, `env_key`, default API base, and capability flags.

**To add a new provider**: (1) add a `ProviderSpec` to `PROVIDERS` in `registry.py`, (2) add a config field to `ProvidersConfig` in `nanobot/config/schema.py`.

Three backend implementations: `AnthropicProvider`, `OpenAICompatProvider` (covers most providers), `AzureOpenAIProvider`.

### Tool System

`nanobot/agent/tools/registry.py` holds `ToolRegistry`. Built-in tools: file operations, shell exec, web search/fetch, message sending, subagent spawn, cron scheduling, and MCP. File/shell tools respect `restrictToWorkspace` config to sandbox access.

### Memory System

Two-layer: `MEMORY.md` (long-term facts, compact) and `HISTORY.md` (timestamped searchable log). `MemoryConsolidator` calls the LLM after each agent turn to extract and update both files. Messages are never modified after writing (cache-friendly for Anthropic prompt caching).

### Skill System

`SkillsLoader` scans `~/.nanobot/workspace/skills/` for directories containing `SKILL.md`. Some skills are `always_skills` (always loaded into context); others are on-demand. Bundled skills live in `nanobot/skills/`.

## Configuration

User config lives at `~/.nanobot/config.json` (Pydantic `BaseSettings`, supports both camelCase and snake_case). The workspace (agent files, memory, skills) defaults to `~/.nanobot/workspace/`.

## Testing Conventions

- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` (set in `pyproject.toml`)
- Tests live in `tests/` mirroring the source structure
- Integration tests hit real code paths; avoid mocking internals

## Branching

- `main`: stable, production-ready
- `nightly`: experimental features; cherry-picked to main weekly
