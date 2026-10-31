# contextwell-core

Memory and semantic retrieval domain for copilot-fusion.

## Features

- **Long-term & Session Memory:** Tools for storing and querying memories (`remember`, `recall`, `list_memories`, `forget`, `update`).
- **Scoping & Lifecycle:** Supports `project` and `global` scopes with optional TTL expiration (`expires_at`, `purge_expired`).
- **Maintenance & Distillation:** Tools for memory stats, compression (`compress_memories`) and export (`export_memories`).

## Retrieval and scope rules

- `recall` uses a SQLite FTS5 index (bm25 ranking over content and tags, prefix matching for tokens of 3+ chars, bonus for exact phrase containment). Scores are relative, not normalized. The index is kept in sync by triggers and rebuilt automatically if it drifts.
- Expired memories (`expires_at` in the past) are never returned by `recall`; `purge_expired` deletes them.
- `global` memories are user-wide preferences/facts. `project` memories belong to one repository and should set `scope_path` to the repo root; query with the same `scope_path` to stay inside it.
- There is no session scope: in-session context is the client's job. Store only what should survive the session.
- Quality is guarded by `tests/test_memory_retrieval_eval.py` (top-3 hit rate threshold on a fixed corpus). Add cases there when retrieval misses something real.
