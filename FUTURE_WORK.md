# Future work

Direction and definition of done live in [`SCOPE.md`](SCOPE.md). Only two tracks remain;
anything else is maintenance (dependency bumps, MCP spec compatibility, bug fixes).

## 1. Memory retrieval — done

FTS5/bm25 `recall`, expiry filtering, written scope rules (`packages/contextwell-core/README.md`),
an eval test (`tests/test_memory_retrieval_eval.py`), and removal of the `rerank` / `reembed_all` stubs.
Embeddings are only worth adding if real misses show up in the eval; add the failing case first.

## 2. Tree-sitter `symbol_search` — done

`packages/contextwell-tools/src/contextwell_tools/symbols.py` indexes Python, JS/TS/JSX/TSX and Go
(definitions incl. methods with `parent`, calls, identifier references), cached by mtime. Limits: matching is
by name with no import/type resolution (results flag `same_name_definitions`). Add a language by adding a
`_Lang` subclass and a grammar dependency; consider LSP only if name-based precision proves insufficient.

## 3. Housekeeping — done

`FUSION_PROFILE` (`core` | `full`) and removal of the tools listed in `SCOPE.md` are implemented.
The only open item is confirming CI is green on Windows; after that, this project is in maintenance.
