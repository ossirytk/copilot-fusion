# Safe editing plan

## Status

- Phase 1 guarded patch editing is implemented as `apply_text_patch`.
- Phase 2 richer operations and conflict diagnostics are implemented in `apply_text_patch`.
- Additional policy controls and advanced patch semantics remain follow-up work.

---

## Goal

Add a minimal write-capable tool so copilot-fusion can move from inspection-only to actual code assistance.

## Why this matters

The current server can inspect, search, and diff, but it cannot make edits.
That leaves a major gap in the "all in one" Copilot workflow.

## MVP shape

- Prefer patch-based edits over whole-file replacement.
- Require explicit path resolution and scope checks.
- Return structured success and failure details.
- Refuse destructive edits that are not explicitly requested.

## MVP steps

1. Decide on the edit model (`apply_patch` style vs full replacement).
2. Define guardrails for file scope and path normalization.
3. Implement the tool in the most appropriate domain or shared layer.
4. Add tests for insert, replace, and rejected invalid edits.

## Key design decisions

- Small, explicit diffs are safer than broad rewrites.
- The tool should remain deterministic and easy to audit.
- Editing needs clear failure modes, not silent fallback behavior.

## Good Copilot session splits

- session 1: API and guardrail design
- session 2: patch application implementation
- session 3: test coverage for valid and invalid edits
- session 4: docs and compatibility updates
