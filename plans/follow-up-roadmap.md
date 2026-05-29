# Follow-up roadmap

The merged baseline now covers the first pass of the original roadmap:

- text distillation: compaction, summarization, remote summarization, and `read_file` compact mode
- safe editing: guarded patches, richer operations, conflict diagnostics, and workspace policy controls
- code navigation: symbol lookup, references, callsites, and lightweight callgraph extraction

## Remaining themes

### Text distillation

- Add comparative quality checks on representative corpora.
- Add guidance for when to use `read_file(compact=true)` vs `text_compact` (drafted in `plans/text-distillation.md`).
- Consider optional model-backed NER/entity extraction.

### Safe editing

- Structured preview responses for dry runs and edit batches are implemented.
- Consider advanced semantics for larger, multi-file edit intents.
- Add policy templates for common workspace layouts if needed.

### Code navigation

- Improve precision/depth of callgraph extraction.
- Expand language-aware parsing beyond the current lightweight heuristics.
- Evaluate indexing/caching if large-repo performance becomes an issue.

## Planning approach

- Keep repo-side plan docs in sync with the merged baseline.
- Split only when a follow-up item deserves its own execution track.
- Prefer small, independently actionable plan files that can be handed to Copilot sessions.

## Next decisions

- Keep this as a consolidated roadmap, or split each theme into its own repo-side plan file?
- Which follow-up theme should be the first implementation target?
