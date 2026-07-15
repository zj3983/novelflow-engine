# Configuration Provider Visibility Design

## Goal

Keep the configuration page focused on settings that affect the selected runtime provider. Codex CLI mode must not show API or per-agent model settings that are ignored by the current CLI adapter. OpenAI-compatible API mode continues to expose the existing advanced configuration.

## Current Behavior

The page always shows API credentials, runtime model strategy, and per-agent endpoint overrides. In Codex CLI mode, the API fields are disabled but remain visible. Model selections are also visible even though the CLI adapter uses `NOVEL_CODEX_MODEL` (or `gpt-5.4`) unless `NOVEL_CODEX_USE_PAYLOAD_MODEL=1` is set outside the application.

## Selected Design

The global provider selector controls which configuration sections are rendered.

### Codex CLI

Show only:

- Model source selector
- Codex CLI command
- CLI connection test and result
- Unified save action and page status

Hide:

- Global API key
- Global API base URL
- Runtime strategy, including global and per-agent model fields
- New-character policy
- All per-agent API overrides and their connection tests

### OpenAI-Compatible API

Show the existing API configuration:

- Global API key and base URL
- Global connection test
- Runtime strategy
- Collapsed per-agent override section
- Unified save action and page status

## State Behavior

Changing provider only changes visibility. It must not clear API credentials, model strategy, or per-agent overrides. Switching back to OpenAI-compatible API restores the previously loaded or edited values.

Saving continues to submit both runtime settings and runtime strategy so hidden values remain stable and backward compatible.

## Component Changes

- `GlobalApiConfigCard` renders API fields only for the OpenAI-compatible provider. Codex CLI keeps its command and connection test.
- `ConfigPageClient` renders `RuntimeStrategyCard` and `AgentOverrideGrid` only when the global provider is `openai`.
- Existing components and API payload shapes remain unchanged.

## Tests

The configuration page end-to-end test will verify:

1. Default Codex CLI mode shows the CLI command and hides API fields, runtime strategy, and Agent overrides.
2. Selecting OpenAI-compatible API reveals API fields, runtime strategy, and the collapsed Agent override control.
3. Expanding Agent overrides still reveals all four existing override cards.

No backend behavior or persistence format changes are required.
