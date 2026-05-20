# copilot-fusion

Unified MCP toolkit that fuses core memory, git workflows, and filesystem/code tools into one server.

## Layout

- `packages/copilot-fusion/` — unified mega-tool MCP server entry point
- `packages/contextwell-core/` — memory and semantic retrieval domain (from contextwell)
- `packages/contextwell-git/` — git workflow domain (from gitpilot)
- `packages/contextwell-tools/` — filesystem/code tooling domain (from toolpilot)
- `packages/shared/` — shared config/utilities used across packages

## Status

Initial migration is active:

- `contextwell-core` exports memory tools (`remember`, `recall`, `list_memories`, etc.)
- `contextwell-git` exports git and gh tools (`git_*`, `gh_*`)
- `contextwell-tools` exports filesystem/code tools (`fs_glob`, `fs_tree`, `text_search`, `json_select`, `yaml_select`, `server_stats`)

## Configuration

Domain registration can be controlled with environment variables:

- `FUSION_ENABLE_CORE` (`1`/`0`, default `1`)
- `FUSION_ENABLE_GIT` (`1`/`0`, default `1`)
- `FUSION_ENABLE_TOOLS` (`1`/`0`, default `1`)

Example:

```bash
FUSION_ENABLE_CORE=0 FUSION_ENABLE_GIT=1 FUSION_ENABLE_TOOLS=1 copilot-fusion
```
