# contextwell-git

Unified VCS and workflow domain for copilot-fusion, providing Git and Jujutsu (`jj`) tooling alongside GitHub CLI helpers.

## Features

- **Dual Git & Jujutsu (jj) Support:** Tools automatically detect whether the workspace is backed by plain Git or a Jujutsu-colocated repository (`.jj` directory + `jj` CLI available).
- **Standard Tool Surface:** Agents continue to call standard Git tool signatures (`git_status`, `git_commit`, `git_diff`, `git_log`, `git_show`, `git_branch`, `git_merge`, `git_stash`, `git_reset`, `git_tag`, `git_remote`, `git_fetch`, `git_pull`, `git_push`) without needing to learn separate JJ commands.
- **JJ Safety & Metadata:** When running in a `.jj` repository, responses are augmented with `backend: "jj"`, `change_id`, `commit_id`, `is_empty`, and conflict indicators (`is_conflicted`).
- **GitHub CLI Integration:** Includes `gh_pr_*` and `gh_issue_*` helpers for seamless pull request and issue management.
- **Health Check:** `fusion_git_health` reports whether the domain is ready, whether `jj` is installed, and the detected default backend.

