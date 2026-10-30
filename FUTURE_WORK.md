# Future work

Direction and definition of done live in [`SCOPE.md`](SCOPE.md). Only two tracks remain;
anything else is maintenance (dependency bumps, MCP spec compatibility, bug fixes).

## 1. Memory retrieval — done

FTS5/bm25 `recall`, expiry filtering, written scope rules (`packages/contextwell-core/README.md`),
an eval test (`tests/test_memory_retrieval_eval.py`), and removal of the `rerank` / `reembed_all` stubs.
Embeddings are only worth adding if real misses show up in the eval; add the failing case first.

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
