# copilot-fusion

Unified MCP server entry point for copilot-fusion, integrating core memory, VCS (Git & Jujutsu), filesystem/code tools, and structured diffs into a single server.

## Overview

- **Entry Point:** Exposes `copilot_fusion.server:create_server()` as the primary FastMCP server.
- **Profiles:** `FUSION_PROFILE=core` (memory + `symbol_search`) or `full` (default, adds the portable file/git/diff/terminal tools).
- **Composable Domains:** Individual domains can be switched off with `FUSION_ENABLE_*`.
- **Health:** `fusion_health` reports the active profile and domains.

