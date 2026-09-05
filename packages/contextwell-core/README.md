# contextwell-core

Memory and semantic retrieval domain for copilot-fusion.

## Features

- **Long-term & Session Memory:** Tools for storing and querying memories (`remember`, `remember_batch`, `remember_file`, `recall`, `list_memories`, `forget`, `update`).
- **Scoping & Lifecycle:** Supports `project` and `global` scopes with optional TTL expiration (`expires_at`, `purge_expired`).
- **Maintenance & Distillation:** Tools for memory stats, compression (`compress_memories`), export (`export_memories`), and vector re-embedding (`reembed_all`).

