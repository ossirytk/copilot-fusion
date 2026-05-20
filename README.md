# copilot-fusion

Unified MCP toolkit that fuses core memory, git workflows, and filesystem/code tools into one server.

## Layout

- `packages/copilot-fusion/` — unified mega-tool MCP server entry point
- `packages/contextwell-core/` — memory and semantic retrieval domain (from contextwell)
- `packages/contextwell-git/` — git workflow domain (from gitpilot)
- `packages/contextwell-tools/` — filesystem/code tooling domain (from toolpilot)
- `packages/shared/` — shared config/utilities used across packages

## Current Architecture

- `copilot-fusion.server:create_server()` is the single registration point for all domains.
- Domain registration is composable and controlled by `FusionConfig` / `FUSION_ENABLE_*` flags.
- Shared infrastructure lives in `copilot_fusion_shared`:
  - `config.py` — runtime domain toggles
  - `paths.py` — path + data directory resolution
  - `commands.py` — subprocess execution wrapper
- `fusion_api_compat` exposes a runtime compatibility matrix against contextwell/gitpilot/toolpilot tool surfaces.

## Overlap Consolidation

The three merged domains had overlap in command execution, path handling, and tool registration concerns.

| Overlap Area | Previous State | Consolidated State |
|---|---|---|
| Path resolution | Reimplemented in each domain | `copilot_fusion_shared.resolve_path` |
| Command execution | Reimplemented in git/tools domains | `copilot_fusion_shared.run_command` |
| Data directory handling | Local-only in memory domain | `copilot_fusion_shared.app_data_dir` |
| Domain toggle config | Local defaults in server | `FusionConfig.from_env()` + `FUSION_ENABLE_*` |
| Tool-surface tracking | Implicit/manual | `fusion_api_compat` + matrix constants |

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
