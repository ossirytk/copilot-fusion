# Text Distillation / Summarization Brainstorm Plan

## Status

- Phase 1 deterministic baseline is implemented as `text_compact`.
- Phase 2 local extractive summarization backend is implemented as `text_summarize`.
- Phase 3 optional remote/model-backed summarization is implemented via `FUSION_TEXT_SUMMARIZER_URL`.
- Optional compaction output is available from `read_file` via `compact=true`.

---

## Goal

Design a capability that extracts essential signal from large text (error logs, web pages, long docs) with predictable output for Copilot workflows.

This document is the source-of-truth plan for the distillation track.

---

## Current State in copilot-fusion

- Existing relevant tools:
  - `read_file` (bounded reading),
  - `text_search` (literal/regex),
  - `text_compact` (deterministic compaction),
  - `text_summarize` (local extractive summarization),
  - `json_select` / `yaml_select` (structured extraction),
- no dedicated entity-centric extraction/NER tool yet.
- Current fused tool surface: **54 tools**.
- Tool budget appears to have room, but UX clarity still matters.

---

## Usage guidance

- Use `text_compact` when you have noisy text and want deterministic high-signal extraction.
- Use `read_file(compact=true)` when you already need bounded file content and want compacted signal in one call.
- Use `text_summarize` when you want a short narrative summary; choose `backend="auto"` when a remote endpoint is configured.
- Prefer `text_search` for exact token/regex discovery rather than summarization.
- Keep `text_compact` for logs, trace output, and mixed technical noise where line selection matters.

---

## Design Principles

1. Deterministic defaults for automation.
2. Strong utility for raw logs and scraped page text.
3. Offline-first baseline (firewall-friendly).
4. Optional quality upgrades via local/remote model backends.
5. Structured output schema (not prose-only).

---

## Option Space

## A) Rule-Based Text Compacting (no ML)

Potential tool:
- `text_compact(text|path, mode, max_points, include_patterns, exclude_patterns)`

Mechanics:
- prioritize lines with `error|warn|fail|exception`,
- detect stacktrace starts/frames,
- collapse repeated patterns,
- extract top regex matches (IDs, URLs, codes),
- return concise structured sections.

Pros:
- deterministic, fast, no external deps.

Cons:
- weaker quality on prose-heavy narrative text.

---

## B) Hybrid: Rule-Based + Optional Model Summarization

Potential tools:
- `text_compact(...)` (always available),
- `text_summarize(...)` (optional backend).

Mechanics:
- phase-1 deterministic extraction,
- optional summarization pass (local model first; remote opt-in),
- return both deterministic artifacts and narrative summary.

Pros:
- robust baseline + higher potential summary quality.

Cons:
- configuration/testing complexity.

---

## C) Extend Existing Tools Instead of New One

Examples:
- `read_file(..., compact=true, strategy="errors-first")`
- `text_search(..., summarize=true, group_by_pattern=true)`

Pros:
- no immediate tool-count increase.

Cons:
- larger, less coherent tool interfaces.

---

## D) Entity-Centric (NER-first)

Potential tool:
- `extract_entities(text|path, entity_types=[...], context_window=...)`

Focus:
- services, hosts, paths, exception types, URLs, CVEs, timestamps,
- optional relation/timeline output.

Pros:
- great for incident/debug workflows.

Cons:
- NER quality/domain coverage complexity.

---

## Selected Direction for MVP Exploration

**Deterministic/offline first.**

Planned exploration path:
1. Phase 1: deterministic `text_compact` concept.
2. Phase 2: optional summarization backend (local-first).

---

## Draft Output Shape (for comparison across options)

```json
{
  "summary": "Short high-signal summary",
  "bullets": ["key point 1", "key point 2"],
  "patterns": [{"pattern": "TimeoutError", "count": 17}],
  "entities": [{"type": "service", "value": "api-gateway"}],
  "stats": {
    "input_lines": 12000,
    "selected_lines": 85,
    "truncated": true
  },
  "backend": "deterministic"
}
```

---

## Risks / Constraints

- Tool sprawl if we add overlapping tools.
- Local model packaging/runtime footprint.
- Non-deterministic model outputs vs testability.
- Privacy concerns for remote APIs.
- Multilingual behavior variance.

---

## Open Questions

1. Primary target first: logs, webpages, or generic long text?
2. Tool shape: standalone (`text_compact`) vs extending existing tools?
3. Should NER be MVP or phase-2?
4. Which quality metric matters most (precision, compression ratio, actionability)?

---

## Idea-Phase Tasks

1. Define 3 canonical scenarios and expected outputs.
2. Decide API shape for MVP exploration.
3. Evaluate deterministic extraction quality on sample corpora.
4. Evaluate local model feasibility (size/startup/latency).
5. Decide NER scope boundary.
