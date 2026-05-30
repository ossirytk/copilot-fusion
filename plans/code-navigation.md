# Code navigation plan

## Status

- Phase 1 lightweight Python symbol lookup is implemented as `symbol_search`.
- Phase 2 JavaScript/TypeScript/JSX/TSX symbol coverage is implemented in `symbol_search`.
- Richer symbol metadata and optional reference scanning are implemented in `symbol_search`.
- Optional function callsite-aware reference classification is implemented in `symbol_search`.
- Lightweight callgraph-level caller/callee/site extraction is implemented in `symbol_search`.
- Mtime-based file caching now keeps repeated navigation queries fast across calls.

---

## Goal

Add symbol-aware navigation so Copilot can move beyond raw file search and better understand project structure.

## Why this matters

The current file and text tools are useful, but they still make the assistant infer too much from plain text.
Symbol-aware lookup would significantly improve productivity on real codebases.

## MVP shape

- Query file symbols by name and kind
- Return paths and line ranges
- Prefer stateless or cacheable queries
- Stay offline-first where possible

## MVP steps

1. Identify the dominant language targets for the repo.
2. Choose a lightweight lookup strategy before adding heavy indexing.
3. Return structured location data instead of prose.
4. Add tests for common project layouts and symbol edge cases.

## Key design decisions

- AST-based lookup is ideal, but the first version can be narrower.
- Navigation should complement `text_search`, not duplicate it.
- Avoid introducing large persistent indexing state unless needed.

## Good Copilot session splits

- session 1: target language and lookup strategy
- session 2: symbol extraction implementation
- session 3: lookup response schema and tests
- session 4: indexing/cache follow-up if needed
