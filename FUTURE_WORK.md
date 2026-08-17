Priority Work?
1. Memory quality — semantic recall is only as useful as what gets embedded. Better memory organization (tagging, decay/aging, scoped namespaces per project) would pay dividends immediately.
2. Symbol search depth — callgraph extraction is there, but cross-file and cross-language dependency tracing (e.g., "who calls this across the whole monorepo?") would be high-value.
3. Context window awareness — tools that proactively compact/summarize based on estimated token budget rather than on-demand.

Complementary technologies worth watching
┌────────────────────────────────┬────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Technology                     │ Fit        │ Notes                                                                                                      │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Tree-sitter                    │ High       │ Language-agnostic AST; upgrade symbol_search beyond regex to real parse trees for C/C++/Rust too           │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ LSP integration                │ High       │ Delegate symbol resolution, go-to-definition, hover to a language server — reliable for compiled languages │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Chroma / Qdrant                │ Medium     │ Replace or augment local embedding store with a persistent vector DB for larger memory sets                │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ LLM-based commit summarization │ Medium     │ Auto-generate semantic commit context for git_log recall                                                   │
├────────────────────────────────┼────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ OpenTelemetry tracing          │ Low-medium │ Instrument tool calls for latency profiling beyond the benchmark script                                    │
└────────────────────────────────┴────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
Random Ideas
1. Git knowledge sources. Could use a local model to create things like:
{
  "tool": "explain_history",
  "symbol": "DeviceConnectionManager"
}
2. Memory into layers. Repo memory vs session memory vs learned memory(something like: Observed 11 incidents involving Windows path length issues.).
3. Local model to query about code?
4. Graph database. Something like: display everything affected by this api.
