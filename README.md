# copilot-fusion

Unified MCP toolkit that fuses core memory, git workflows, filesystem/code tools, and structured diffs into one server.

## Layout

- `packages/copilot-fusion/` — unified mega-tool MCP server entry point
- `packages/contextwell-core/` — memory and semantic retrieval domain (from contextwell)
- `packages/contextwell-git/` — git workflow domain (from gitpilot)
- `packages/contextwell-tools/` — filesystem/code tooling domain (from toolpilot)
- `packages/contextwell-diff/` — structured diff domain (from diffpilot)
- `packages/shared/` — shared config/utilities used across packages

## Architecture

- `copilot_fusion.server:create_server()` is the single registration point for all domains.
- `FusionConfig` (`FUSION_PROFILE`, `FUSION_ENABLE_*`) decides what is registered.
- Shared infrastructure lives in `copilot_fusion_shared`: `config.py` (profile/toggles), `paths.py` (path + data dir), `commands.py` (subprocess wrapper).

## Profiles

Set `FUSION_PROFILE` to choose the tool surface:

| Profile | Tools | Use when |
|---|---|---|
| `full` (default) | everything below | VS Code / Windows / WSL, or any client without strong native file and shell tools |
| `core` | memory tools, `symbol_search`, `fusion_health` | Copilot CLI, which already has native file, search, edit, git and shell tools |

`FUSION_ENABLE_CORE|GIT|TOOLS|DIFF` can still switch individual domains off.

## Tools

**Core (both profiles)**

| Group | Tools |
|---|---|
| Memory | `remember`, `recall`, `list_memories`, `update`, `forget`, `compress_memories`, `export_memories`, `memory_stats`, `purge_expired` |
| Code navigation | `symbol_search` (Tree-sitter: Python, JS/TS/JSX/TSX, Go; definitions, references, callers/callees) |
| Server | `fusion_health` |

**Portable layer (`full` only)**

| Group | Tools |
|---|---|
| Files and text | `fs_glob`, `read_file`, `text_search`, `apply_text_patch`, `text_compact`, `text_summarize`, `server_stats` |
| Git / Jujutsu | `git_status`, `git_diff`, `git_commit`, `git_log`, `git_show`, `git_branch`, `git_merge`, `git_stash`, `git_reset`, `git_tag`, `git_remote`, `git_fetch`, `git_pull`, `git_push`, `fusion_git_health` |
| GitHub | `gh_pr_create`, `gh_pr_list`, `gh_pr_view`, `gh_issue_create`, `gh_issue_list`, `gh_issue_view` |
| Structured diff | `diff_staged`, `diff_refs`, `summarize_diff` |
| Terminal | `terminal_exec`, `terminal_start`, `terminal_status`, `terminal_stop` (allowlist only, see below) |

Removed in the scope cleanup (see `SCOPE.md`): `fs_tree`, `json_select`, `yaml_select`, `file_hash`,
`remember_file`, `remember_batch`, `apply_text_patch_batch`, `diff_files`, `fusion_core_health`,
`fusion_tools_health`, `fusion_diff_health`, `fusion_api_compat`.

## Typical flows

- **Find, read, edit:** `symbol_search(query=...)` returns `path`, `line`, `end_line`; pass those to `read_file` (or the client's view tool), then `apply_text_patch`.
- **Who calls this:** `symbol_search(query=..., kinds=["function"], include_callgraph=True)`.
- **Large logs:** `text_compact` for deterministic signal lines, `text_summarize` for a short narrative.
- **Remember across sessions:** `remember(content, scope="project", scope_path=<repo root>)`, then `recall(query)`.

## Configuration

Registration is controlled with environment variables:

- `FUSION_PROFILE` (`full`/`core`, default `full`)
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
MCP client config and keep prompts unchanged. 

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

For command-level benchmarking (startup process), use `hyperfine`:

```bash
hyperfine --warmup 2 "uv run python scripts/benchmark_fusion.py"
```

### Latest local baseline

| Metric | Mean |
|---|---:|
| `create_server_ms` | 44.702 |
| `list_tools_ms` | 0.720 |
| `fusion_health_ms` | 0.749 |
| `tool_count` | 46 (`full`), 11 (`core`) |
