# Future work backlog

This file is the agent-facing backlog for follow-up work in `copilot-fusion`.

## Planning rule

Main priority: make the tool surface smaller and more uniform.

Use each section below as a standalone assignment for a future Copilot session.
Prefer small, independently shippable changes with clear acceptance criteria.

---

## A. Refinements to existing features

These items improve capabilities that already exist in the repository today.

### A1. Shrink and unify the tool surface

**Why**
- Too many tools overlap in search, read, patch, and diff workflows.
- A smaller set of primitives will be easier for both humans and agents to learn.

**Deliverables**
- Inventory overlapping tools across the merged domains.
- Propose a target surface with fewer, clearer primitives.
- Identify deprecated aliases that should remain for compatibility.
- Update `fusion_api_compat` and user-facing docs to reflect the new shape.

**Acceptance criteria**
- Common file-inspection and editing workflows can be explained with fewer tool names than today.
- Compatibility notes clearly distinguish preferred tools from legacy aliases.

**Good Copilot session splits**
- session 1: overlap audit and target tool map
- session 2: compatibility and aliasing plan
- session 3: implementation of the first consolidation slice
- session 4: docs and migration guidance

### A2. Improve search → read → edit composability

**Why**
- Tool outputs should feed into each other without extra translation or guesswork.
- Agents work better when path and range data stays structured end to end.

**Deliverables**
- Standardize path fields, span/range fields, and identifier naming across search and read tools.
- Make search outputs easier to pass directly into patch/edit operations.
- Document the preferred end-to-end flows for common tasks.

**Acceptance criteria**
- A search result can be used as input to a read or edit flow with little or no reshaping.
- Path handling is consistent across domains.

**Good Copilot session splits**
- session 1: output-shape audit for search/read/edit tools
- session 2: schema cleanup for one workflow family
- session 3: integration tests and examples

### A3. Strengthen previews and dry runs for edits

**Why**
- Safer batch editing needs reliable previews before any write is applied.
- Existing preview support should become easier to trust and easier to consume.

**Deliverables**
- Tighten dry-run behavior for single-file and multi-file edits.
- Return structured previews that are stable enough for agent automation.
- Improve failure diagnostics when a preview cannot be produced cleanly.

**Acceptance criteria**
- Preview output is consistent across edit tools.
- Batch edits can be reviewed before apply with clear per-file results.

**Good Copilot session splits**
- session 1: preview response design
- session 2: single-file preview consistency
- session 3: batch preview consistency and error handling

### A4. Normalize outputs, naming, and path formats

**Why**
- More opinionated result shapes reduce agent guesswork.
- Consistent naming lowers the cognitive cost of switching between domains.

**Deliverables**
- Define conventions for path format, field names, result envelopes, and status reporting.
- Apply the conventions to the highest-traffic tools first.
- Document the conventions in a short reference.

**Acceptance criteria**
- Equivalent concepts use the same names across tool families.
- The preferred path format is explicit and consistently returned.

**Good Copilot session splits**
- session 1: conventions draft
- session 2: update shared helpers and the first tool set
- session 3: compatibility/doc cleanup

### A5. Improve agent-facing docs with concrete flow examples

**Why**
- Short examples are more useful than broad capability descriptions.
- Better docs should reduce misuse of overlapping tools.

**Deliverables**
- Add concise examples for the most common flows:
  - find a symbol, inspect it, then patch it
  - search text, narrow results, then read a file
  - preview a batch edit before apply
- Keep examples aligned with the preferred, reduced tool surface.

**Acceptance criteria**
- A new agent can follow the docs to complete common workflows without extra interpretation.
- Examples use the same naming and result shapes described elsewhere.

**Good Copilot session splits**
- session 1: pick top workflows and draft examples
- session 2: wire examples into README/plan docs
- session 3: consistency pass after tool-surface cleanup

### A6. Improve memory quality and organization

**Why**
- Memory recall quality depends on what gets stored and how it is organized.
- The existing memory domain would benefit from better structure and retrieval quality.

**Deliverables**
- Evaluate tagging, scoped namespaces, and aging/decay strategies.
- Define how repository, session, and longer-lived learned memory should differ.
- Consider whether a persistent vector store is warranted for larger memory sets.

**Acceptance criteria**
- Memory organization rules are explicit.
- Retrieval quality can be evaluated on representative examples.

**Good Copilot session splits**
- session 1: memory-organization design
- session 2: retrieval-quality evaluation harness
- session 3: storage/backend follow-up if needed

### A7. Deepen symbol search and code navigation

**Why**
- Current symbol search is useful, but deeper cross-file and cross-language tracing would add a lot of value.
- Compiled-language support should rely less on regex-style fallbacks over time.

**Deliverables**
- Improve cross-file dependency tracing and whole-repo caller/callee discovery.
- Evaluate Tree-sitter and LSP-backed resolution where they improve reliability.
- Expand language-aware navigation where current coverage is shallow.

**Acceptance criteria**
- Cross-file “who calls this?” style queries work more reliably across the monorepo.
- Navigation accuracy improves for non-Python languages.

**Good Copilot session splits**
- session 1: gap analysis on current symbol search behavior
- session 2: parser/LSP spike
- session 3: one language-family rollout

### A8. Make context compaction more proactive

**Why**
- Context-window awareness should happen before a session gets into trouble.
- Existing compaction/summarization features could be more automatic and budget-aware.

**Deliverables**
- Add token-budget-aware compaction triggers or guidance.
- Define when to compact, summarize, or keep raw context.
- Evaluate comparative quality on representative corpora.

**Acceptance criteria**
- Compaction behavior is guided by explicit token-budget rules.
- Docs explain when to use each distillation path.

**Good Copilot session splits**
- session 1: token-budget policy design
- session 2: quality-evaluation pass
- session 3: docs and workflow guidance

---

## B. New feature tracks

These items introduce capabilities that do not exist yet as first-class features.

### B1. Git-aware history explanation

**Goal**
- Add a knowledge-oriented history tool that can explain how a symbol or subsystem evolved.

**Example shape**
```json
{
  "tool": "explain_history",
  "symbol": "DeviceConnectionManager"
}
```

**Deliverables**
- Define the query model for symbol- or path-based history explanations.
- Prototype semantic commit or change summarization.
- Decide whether local-model summarization is sufficient or optional.

**Good Copilot session splits**
- session 1: API shape and scope
- session 2: git data extraction
- session 3: summarization and response format

### B2. Impact graph / dependency exploration

**Goal**
- Add a graph-oriented view of what code, files, or APIs are affected by a change.

**Deliverables**
- Define a query and result format for “what is affected by this API?” style questions.
- Evaluate whether a graph database is justified or whether an internal graph layer is enough.
- Start with one high-value impact view before expanding.

**Good Copilot session splits**
- session 1: graph use-case definition
- session 2: data model and prototype
- session 3: first query/tool rollout

### B3. Local-model code Q&A

**Goal**
- Explore whether a local model can answer codebase questions cheaply and privately using fusion data sources.

**Deliverables**
- Define the boundary between deterministic tools and model-backed answers.
- Prototype one narrow workflow, such as repository Q&A over indexed code.
- Measure quality versus direct tool composition.

**Good Copilot session splits**
- session 1: scope and safeguards
- session 2: prototype integration
- session 3: evaluation and go/no-go decision

---

## C. Enablers worth evaluating

These are not commitments by themselves, but they map cleanly to the tracks above.

| Technology | Likely fit | Best-aligned tracks |
|---|---|---|
| Tree-sitter | High | A7, B2 |
| LSP integration | High | A7, B2 |
| Chroma / Qdrant | Medium | A6 |
| LLM-based commit summarization | Medium | B1 |
| OpenTelemetry tracing | Low-medium | A1, A2, A3 |

---

## Suggested implementation order

1. A1. Shrink and unify the tool surface
2. A2. Improve search → read → edit composability
3. A3. Strengthen previews and dry runs for edits
4. A4. Normalize outputs, naming, and path formats
5. A5. Improve agent-facing docs with concrete flow examples
6. A6. Improve memory quality and organization
7. A7. Deepen symbol search and code navigation
8. A8. Make context compaction more proactive
9. B1-B3 as separate feature investments after the core surface is simpler
