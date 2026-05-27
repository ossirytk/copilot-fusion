# copilot-fusion

Unified MCP toolkit that fuses core memory, git workflows, filesystem/code tools, and structured diffs into one server.

## Layout

- `packages/copilot-fusion/` — unified mega-tool MCP server entry point
- `packages/contextwell-core/` — memory and semantic retrieval domain (from contextwell)
- `packages/contextwell-git/` — git workflow domain (from gitpilot)
- `packages/contextwell-tools/` — filesystem/code tooling domain (from toolpilot)
- `packages/contextwell-diff/` — structured diff domain (from diffpilot)
- `packages/shared/` — shared config/utilities used across packages

## Current Architecture

- `copilot_fusion.server:create_server()` is the single registration point for all domains.
- Domain registration is composable and controlled by `FusionConfig` / `FUSION_ENABLE_*` flags.
- Shared infrastructure lives in `copilot_fusion_shared`:
  - `config.py` — runtime domain toggles
  - `paths.py` — path + data directory resolution
  - `commands.py` — subprocess execution wrapper
- `fusion_api_compat` exposes a runtime compatibility matrix against contextwell/gitpilot/toolpilot/diffpilot tool surfaces.

## Overlap Consolidation

The merged domains had overlap in command execution, path handling, and tool registration concerns.

| Overlap Area | Previous State | Consolidated State |
|---|---|---|
| Path resolution | Reimplemented in each domain | `copilot_fusion_shared.resolve_path` |
| Command execution | Reimplemented in git/diff domains | `copilot_fusion_shared.run_command` |
| Data directory handling | Local-only in memory domain | `copilot_fusion_shared.app_data_dir` |
| Domain toggle config | Local defaults in server | `FusionConfig.from_env()` + `FUSION_ENABLE_*` |
| Tool-surface tracking | Implicit/manual | `fusion_api_compat` + matrix constants |

## Status

Initial migration is active:

- `contextwell-core` exports memory tools (`remember`, `recall`, `list_memories`, etc.)
- `contextwell-git` exports git and gh tools (`git_*`, `gh_*`)
- `contextwell-tools` exports filesystem/code tools (`fs_glob`, `fs_tree`, `text_search`, `text_compact`, `text_summarize`, `apply_text_patch`, `symbol_search`, `read_file`, `json_select`, `yaml_select`, `file_hash`, `server_stats`)
- `contextwell-diff` exports structured diff tools (`diff_staged`, `diff_refs`, `diff_files`, `summarize_diff`)

## Configuration

Domain registration can be controlled with environment variables:

- `FUSION_ENABLE_CORE` (`1`/`0`, default `1`)
- `FUSION_ENABLE_GIT` (`1`/`0`, default `1`)
- `FUSION_ENABLE_TOOLS` (`1`/`0`, default `1`)
- `FUSION_ENABLE_DIFF` (`1`/`0`, default `1`)

Example:

```bash
FUSION_ENABLE_CORE=0 FUSION_ENABLE_GIT=1 FUSION_ENABLE_TOOLS=1 FUSION_ENABLE_DIFF=1 copilot-fusion
```

Base MCP config example is provided in `mcp-config.example.json`.

## Migration Guide (contextwell + gitpilot + toolpilot → copilot-fusion)

1. Install and configure `copilot-fusion` as your primary server.
2. Disable `contextwell`, `gitpilot`, `toolpilot`, and `diffpilot` in your MCP client config.
3. Keep the same tool names in prompts; the merged server preserves the original surface for the migrated domains.
4. Validate coverage with `fusion_api_compat` after startup.

### Tool-surface status

| Source server | Coverage in fusion | Notes |
|---|---|---|
| `contextwell` | Full initial surface | Implemented in `contextwell-core` domain |
| `gitpilot` | Full initial surface | Implemented in `contextwell-git` domain |
| `toolpilot` | Full initial surface | Implemented in `contextwell-tools` domain (with `git_log` routed via merged git domain) |
| `diffpilot` | Full initial surface | Implemented in `contextwell-diff` domain |

## Optional Tools Strategy

The non-core pilot tools remain standalone and can run beside fusion:

- `feedpilot`
- `benchpilot`
- `envpilot`
- `httppilot`
- `shellpilot`
- `snippetpilot`
- `diffpilot`

Use `mcp-config.optional.example.json` as a template when you want fusion + optional tools together.

## Roadmap

The next feature tracks are being implemented one at a time:

- text distillation / compaction (phase 1 `text_compact` + phase 2 local extractive `text_summarize` are implemented)
- safe file editing (phase 1 guarded `apply_text_patch` is implemented)
- code navigation / symbol awareness (phase 1 lightweight Python `symbol_search` is implemented)

See `plans/README.md` for the implementation plan files.

## Performance Benchmarking

Run the local benchmark harness:

```bash
uv run python scripts/benchmark_fusion.py
```

This reports average latency for:

- `create_server`
- `list_tools`
- `fusion_health`
- `fusion_api_compat`

For command-level benchmarking (startup process), use `hyperfine`:

```bash
hyperfine --warmup 2 "uv run python scripts/benchmark_fusion.py"
```

### Latest local baseline

| Metric | Mean |
|---|---:|
| `create_server_ms` | 64.423 |
| `list_tools_ms` | 0.856 |
| `fusion_health_ms` | 0.625 |
| `fusion_api_compat_ms` | 0.564 |
| `tool_count` | 54 |
