# Scope and definition of done

copilot-fusion is an MCP server for Copilot clients (Copilot CLI on Linux, VS Code on Windows/WSL).
Clients now ship strong native file, search, edit and shell tools, so fusion only keeps what
they do not provide. This file is the contract for when the project is "done".

## Core (the reason to exist)

1. **Memory** (`remember`, `recall`, `list_memories`, `update`, `forget`, plus admin tools)
   - Cross-session, scoped (repo / user / session) storage.
   - Retrieval is real: SQLite FTS5/bm25 (embeddings only if the eval demands them).
   - Retrieval quality is checked by a small eval set in `tests/`.
2. **Code navigation** (`symbol_search`)
   - Tree-sitter backed definitions, references and callers.
   - Python and TS/JS required, plus one more language.

## Portable profile (`FUSION_PROFILE=full`, default off in CLI-only setups)

Cross-platform, structured, bounded wrappers for clients without a reliable shell:
`git_*`, `gh_*`, `diff_staged`/`diff_refs`, `terminal_*` (allowlisted), `read_file`, `text_search`, `fs_glob`,
and `text_compact`/`text_summarize` (kept for reducing large logs and large files; useful, not critical).
No new tools are added here; behavior changes only for bugs and safety.

## Deprecated (remove after one release with a warning)

`fs_tree`, `json_select`, `yaml_select`, `file_hash`, `remember_file`, `remember_batch`,
`apply_text_patch_batch`, `diff_files`, `git_diff`,
the `fusion_*_health` family, and `fusion_api_compat`
(migration from contextwell/gitpilot/toolpilot/diffpilot is complete).

## Explicitly out of scope

History explanation, impact graphs, local-model Q&A, proactive compaction,
and any new tool that duplicates a client-native capability.

## Done when

- [x] `recall` uses real retrieval (FTS5/bm25) and has an eval test.
- [x] `symbol_search` uses Tree-sitter for Python, TS/JS and Go.
- [ ] `FUSION_PROFILE` (`core` | `full`) gates the portable profile.
- [ ] Deprecated tools are removed; README and `FUTURE_WORK.md` match this file.
- [ ] CI is green on Linux and Windows.

After that: dependency updates, MCP spec compatibility and bug fixes only.
