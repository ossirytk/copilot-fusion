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

Terminal execution is available through `terminal_exec`, `terminal_start`,
`terminal_status`, and `terminal_stop`. It is disabled by default until an
administrator configures `FUSION_EXEC_ALLOWLIST` as a JSON array of exact
argument arrays. The working directory defaults to the server's startup
directory and can be narrowed or changed with `FUSION_EXEC_WORKSPACE`.

For example, this configuration approves only `git status --short` and `pytest
-q`; callers cannot add or change command arguments:

```bash
FUSION_EXEC_WORKSPACE=/path/to/repo \
FUSION_EXEC_ALLOWLIST='[["git","status","--short"],["pytest","-q"]]' \
copilot-fusion
```

Commands are launched without an implicit shell, must use a working directory
inside the configured workspace, and return bounded output (8,000 characters
per stream by default, configurable up to 20,000). `terminal_exec` defaults to
a 30-second timeout, configurable up to 300 seconds; use the start/status/stop
tools for longer-running commands. Known destructive or privileged commands
are blocked. Allowlisted shells/interpreters (`sh`, `bash`, `python`, `node`,
etc.), permission/ownership changes (`chmod`, `chown`), and mutating git
operations (`commit`, `push`, `merge`, `rebase`, `reset`, `switch`, etc.)
require an explicit `confirm_unsafe=true` argument on `terminal_exec` or
`terminal_start`. Some destructive git forms remain blocked even with
confirmation (for example `git clean -f*`, `git reset --hard`,
`git branch -d/-D`, and force/delete `git push` flags). This is an allowlist
and workspace guard, not an operating-system sandbox; approved commands retain
the server user's normal permissions.

Example:

```bash
FUSION_ENABLE_CORE=0 FUSION_ENABLE_GIT=1 FUSION_ENABLE_TOOLS=1 FUSION_ENABLE_DIFF=1 copilot-fusion
```

Base MCP config example is provided in `mcp-config.example.json`.

## Scope and Roadmap

See [`SCOPE.md`](SCOPE.md) for what this server is for and when it is done, and
[`FUTURE_WORK.md`](FUTURE_WORK.md) for the two remaining tracks (memory retrieval and
Tree-sitter `symbol_search`). Everything else is maintenance. `plans/` holds historical
design notes for the implemented features.

Fusion's unique value is cross-session memory and code navigation. The file, git, diff and
terminal tools are a portable, bounded layer for clients without a reliable shell (VS Code on
Windows/WSL); prefer the client's native tools when they are available.

## Migrating from contextwell / gitpilot / toolpilot / diffpilot

These servers are merged into fusion with the same tool names. Disable the old servers in your
MCP client config and keep prompts unchanged. `fusion_api_compat` reports the surface at runtime
(scheduled for removal, see `SCOPE.md`).

## Optional standalone servers

`feedpilot`, `benchpilot`, `envpilot`, `httppilot`, `shellpilot` and `snippetpilot` are separate
projects that can run beside fusion; see `mcp-config.optional.example.json`. They are not part of
this repository.

## Copilot skill guidance

- Disable the legacy overlapping servers (`contextwell`, `gitpilot`, `toolpilot`, `diffpilot`).
- Use `recall` / `list_memories` for remembered context across sessions.
- Use `text_compact` / `text_summarize` (or `read_file(compact=true)`) for large logs and files.
- In clients with native file/search/edit/shell tools, prefer those over the fusion equivalents.

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
| `tool_count` | 59 |
