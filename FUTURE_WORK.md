# Future work

Direction and definition of done live in [`SCOPE.md`](SCOPE.md). Only two tracks remain;
anything else is maintenance (dependency bumps, MCP spec compatibility, bug fixes).

## 1. Memory retrieval

**Why:** `recall` is substring/tag scoring; `rerank` is ignored and `reembed_all` is a stub.

**Deliverables**
- Small eval set (query → expected memories) in `tests/`.
- Real retrieval: SQLite FTS5 as the baseline; embeddings (e.g. sqlite-vec) only if the eval shows FTS5 is insufficient.
- Written scope rules for repo / user / session memories, and optional expiry.
- Remove or implement `rerank` and `reembed_all`.

**Done when:** the eval passes with a stated threshold and the stub parameters are gone.

## 2. Tree-sitter `symbol_search`

**Why:** current Python AST + JS/TS regex coverage is shallow for references and callers.

**Deliverables**
- Tree-sitter backend for definitions, references and callers.
- Python and TS/JS first, then one additional language.
- Keep the existing result shape (path, line/range, name) so results feed `read_file` and `apply_text_patch`.

**Done when:** cross-file "who calls this?" works for the three languages, with tests.

## 3. Housekeeping required by SCOPE.md

- Add `FUSION_PROFILE` (`core` | `full`) gating the portable profile.
- Deprecate with a warning, then remove, the tools listed under "Deprecated" in `SCOPE.md`.
- Keep README and `plans/` in line with the above.
