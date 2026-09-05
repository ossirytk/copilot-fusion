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
- `contextwell-git` exports unified VCS tools supporting Git and Jujutsu (`jj`) in colocated repositories, plus GitHub CLI helpers (`git_*`, `gh_*`)
- `contextwell-tools` exports filesystem/code tools (`fs_glob`, `fs_tree`, `text_search`, `text_compact`, `text_summarize`, `apply_text_patch`, `apply_text_patch_batch`, `symbol_search`, `read_file`, `json_select`, `yaml_select`, `file_hash`, `server_stats`)
- `contextwell-diff` exports structured diff tools (`diff_staged`, `diff_refs`, `diff_files`, `summarize_diff`)

## Tool Surface Guide

The full tool count is intentionally kept small. This section distinguishes the **preferred** minimal surface from **legacy aliases** that are retained for compatibility.

### Preferred tools

Reach for these tools first. They cover the common workflows with the least overlap.

| Group | Tools |
|---|---|
| Memory | `remember`, `recall`, `list_memories`, `forget`, `update` |
| File inspection | `fs_glob`, `fs_tree`, `read_file` |
| Search & navigation | `text_search`, `symbol_search` |
| Text distillation | `text_compact`, `text_summarize` |
| Editing | `apply_text_patch` |
| Git | `git_status`, `git_commit`, `git_log`, `git_show`, `git_branch`, `git_fetch`, `git_pull`, `git_push` |
| GitHub | `gh_pr_create`, `gh_pr_list`, `gh_pr_view`, `gh_issue_create`, `gh_issue_list`, `gh_issue_view` |
| Structured diff | `diff_staged`, `diff_refs`, `summarize_diff` |
| Server | `fusion_health`, `fusion_api_compat` |

### Legacy aliases (compatibility only)

These tools are present but have a preferred alternative for common use cases.

| Legacy tool | Preferred alternative | Notes |
|---|---|---|
| `git_diff` | `diff_staged` or `diff_refs` | Legacy raw diff; prefer structured diff-domain tools for parsed output |
| `diff_files` | `diff_refs` | `diff_refs` with a path filter is more explicit |
| `remember_file` | `read_file` + `remember` | Convenience wrapper; explicit two-step is clearer |
| `remember_batch` | `remember` | Useful for bulk imports; not a primary workflow tool |
| `apply_text_patch_batch` | `apply_text_patch` | Use batch form only when multi-file atomicity is needed |
| `json_select` | `read_file` | `read_file` covers most structured-data reads |
| `yaml_select` | `read_file` | `read_file` covers most structured-data reads |

`fusion_api_compat` returns both `preferred_surface` and `legacy_aliases` at runtime so agents can
always discover the current classification.

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
| `toolpilot` | Full initial surface | Implemented in `contextwell-tools` domain |
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

- text distillation / compaction (phase 1 `text_compact`, phase 2 local extractive `text_summarize`, phase 3 remote/model-backed `text_summarize` via `FUSION_TEXT_SUMMARIZER_URL`, optional summary entities, and optional `read_file` compact mode are implemented)
- safe file editing (phase 1 guarded `apply_text_patch` + phase 2 richer edit ops/diagnostics + structured previews + multi-file batch editing are implemented)
- code navigation / symbol awareness (phase 1 Python + phase 2 JS/TS/JSX/TSX coverage, callsite references, caller/callee callgraph extraction, and mtime-based file caching in `symbol_search` are implemented)
- unified VCS with Jujutsu (jj) colocation (automatic `.jj` workspace detection, semantic mapping of `git_*` operations to native `jj` commands, first-class conflict metadata, and `fusion_git_health` status reporting are implemented)

## Copilot skill guidance

For best model performance with this server:

- disable legacy overlapping skills (`contextwell`, `gitpilot`, `toolpilot`, `diffpilot`) when `copilot-fusion` is enabled
- guide the model to prefer fusion tools over internal assumptions for memory and compaction:
  - use `recall` / `list_memories` for remembered context
  - use `text_compact` for deterministic signal extraction
  - use `text_summarize` for narrative summary
  - use `read_file(compact=true)` when bounded file reads and compaction are both needed in one call

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
| `create_server_ms` | 64.911 |
| `list_tools_ms` | 1.043 |
| `fusion_health_ms` | 0.677 |
| `fusion_api_compat_ms` | 0.579 |
| `tool_count` | 55 |
