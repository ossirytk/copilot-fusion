# Jujutsu (jj) and Git Colocation Support Plan

## Status

- Implemented unified Git & Jujutsu (jj) VCS tooling under `contextwell-git`.
- Colocated repository detection and JJ translation adapter are active across all Git MCP tools (`git_status`, `git_commit`, `git_diff`, `git_log`, `git_show`, `git_branch`, `git_merge`, `git_stash`, `git_reset`, `git_tag`, `git_remote`, `git_fetch`, `git_pull`, `git_push`).
- Health reporting via `fusion_git_health` verifies JJ presence and default backend.
- End-to-end integration and unit test suite verified under `tests/test_jujutsu_colocation.py`.

---

## Goal

Enable `contextwell-git` tools to seamlessly operate in Jujutsu-colocated repositories (`.jj` present alongside `.git`) without requiring agents to learn new tool names or JJ-specific commands. The existing Git tool signatures (`git_status`, `git_commit`, `git_diff`, etc.) will automatically delegate to Jujutsu when colocation is detected, augmenting responses with JJ safety guarantees and metadata.

## Why This Matters

1. **LLM Familiarity vs VCS Innovation**: Copilot and LLM agents are trained extensively on standard Git workflows and commands. Jujutsu provides superior VCS semantics (anonymous branching, working-copy commits, operation logs, first-class conflicts), but LLMs rarely invoke `jj` correctly on their own.
2. **Safe Rollback & Agent Recovery**: Agents frequently make wrong turns. Jujutsu's operation log (`jj undo` / `jj op log`) enables foolproof state recovery compared to destructive `git reset --hard`.
3. **Non-blocking Conflicts**: Conflicts in `jj` do not leave working directories in broken conflict marker states that fail builds or confuse agents.
4. **Zero Workflow Friction**: Repositories colocated with `jj git init --colocate` can be managed by agents using standard Git tool calls while developers enjoy native JJ benefits.

---

## Architecture & Detection

### 1. Backend Detection Strategy

At runtime, for each tool invocation on a target `path`:
1. Check if `jj` binary is available on the system (`shutil.which("jj")`).
2. Probe if `path` belongs to a Jujutsu workspace by checking for `.jj` directory or running `jj root --quiet`.
3. Select the execution backend:
   - **`jj-colocated`**: `.jj` directory and `.git` exist, and `jj` CLI is present.
   - **`git`**: standard Git repository or `jj` not installed.

```
       Agent (calls git_status, git_commit, etc.)
                          │
                          ▼
            [contextwell-git registry]
                          │
              Runtime Workspace Probe
             ┌────────────┴────────────┐
             ▼                         ▼
      [.jj + jj found]           [Plain Git / fallback]
             │                         │
     JJ Translation Adapter       Direct Git Execution
     (jj describe, jj status...)  (git status, git commit...)
```

### 2. Semantic Mapping (Git ↔ Jujutsu)

| Tool Function | Plain Git Behavior | Colocated Jujutsu Equivalent | Extra Metadata Returned |
| :--- | :--- | :--- | :--- |
| `git_status` | `git status --short --branch` | `jj status` + `jj log -r @ -T ...` | `backend: "jj"`, `change_id`, `is_conflicted`, `parent_change_id` |
| `git_diff` | `git diff [--staged] [-- file]` | `jj diff [-- file]` (staged ignored as working copy is commit) | `backend: "jj"` |
| `git_commit` | `git add -A` + `git commit -m` | `jj describe -m <msg>` + `jj new` | `backend: "jj"`, `change_id`, `commit_id` |
| `git_log` | `git log -n ... --pretty=...` | `jj log -r ... --limit ...` (formatted) | `backend: "jj"` |
| `git_show` | `git show <ref>` | `jj show <ref/change_id>` | `backend: "jj"` |
| `git_branch` | `git switch / branch` | `jj bookmark create / set` & `jj edit / new` | `backend: "jj"`, `bookmarks` |
| `git_merge` | `git merge <branch>` | `jj new @ <branch>` | `backend: "jj"`, `change_id` |
| `git_stash` | `git stash push / pop` | `jj new` (push) / `jj squash` (pop) | `backend: "jj"` |
| `git_reset` | `git reset --<mode> <ref>` | `jj undo` or `jj restore -r <ref>` | `backend: "jj"`, `op_id` |
| `git_remote` / `git_fetch` | `git fetch ...` | `jj git fetch ...` | `backend: "jj"` |
| `git_push` | `git push ...` | `jj git push ...` | `backend: "jj"` |

---

## Implementation Phases

### Phase 1: Backend Detection & JJ Runner Utility
- Add helper `detect_vcs_backend(path: str) -> str` (`"jj"` | `"git"`).
- Implement `run_jj(args: list[str], path: str)` in `contextwell_git` or `copilot_fusion_shared`.
- Add health check indicator in `fusion_git_health` reporting whether `jj` binary is detected.

### Phase 2: Read-Only Tool Routing
- Update `git_status`, `git_diff`, `git_log`, and `git_show` to delegate to `jj` when backend is `"jj"`.
- Ensure standard output keys (`status`, `diff`, `raw`) remain present so existing client expectations are preserved.
- Attach structured JJ details (`change_id`, `conflict`, `bookmarks`) in the returned dictionary.

### Phase 3: Write / Mutation Operations
- Implement `git_commit` via `jj describe` + `jj new` (or bookmark movement).
- Implement `git_branch` translation (mapping Git branch concepts to JJ bookmarks & revisions).
- Implement `git_reset` mapping with safe fallback to `jj undo` or `jj restore`.
- Add `git_stash` and `git_merge` JJ equivalents.

### Phase 4: Colocation & Remote Synchronization
- Ensure `jj git export` / automatic snapshotting is respected before external Git tools or pushes run.
- Route `git_fetch`, `git_pull`, `git_push` through `jj git fetch` and `jj git push`.
- Gracefully handle detached / non-colocated edge cases.

### Phase 5: Testing & Verification
- Unit and integration tests with mocked `jj` outputs.
- End-to-end temporary directory tests initializing `jj git init --colocated` if `jj` binary is present on test runner.
- Quality gates validation (`uv run ruff check .`, `uv run pytest`).

---

## Edge Cases & Guardrails

1. **Working Copy is Already a Commit**: In JJ, the working directory is always an open commit `@`. Agents expecting to "stage" files with `git add` can simply treat `git_commit(add_all=True)` as `jj describe -m <msg>` followed by `jj new`.
2. **First-class Conflicts**: If a merge creates conflicts, `jj status` will flag `has_conflicts=True`. The tool response should clearly highlight conflicting paths without breaking tool execution.
3. **Missing `jj` binary**: If `.jj` directory exists but `jj` is not in `$PATH`, fall back to standard `git` CLI (since the repo is colocated and `.git` is valid) and include a warning.

---

## Good Copilot Session Splits

- **Session 1 (Scaffolding & Detection)**: Implement `detect_vcs_backend` and `run_jj` runner helpers with unit tests.
- **Session 2 (Read-only tools)**: Implement and test JJ translation for `git_status`, `git_diff`, `git_log`, `git_show`.
- **Session 3 (Write operations)**: Implement and test `git_commit`, `git_branch`, `git_reset`, `git_merge`, `git_stash`.
- **Session 4 (Remotes & Sync)**: Implement `git_fetch`, `git_pull`, `git_push` via `jj git` and end-to-end colocated workflow tests.
