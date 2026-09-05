# copilot-fusion

Unified MCP server entry point for copilot-fusion, integrating core memory, VCS (Git & Jujutsu), filesystem/code tools, and structured diffs into a single server.

## Overview

- **Entry Point:** Exposes `copilot_fusion.server:create_server()` as the primary FastMCP server.
- **Composable Domains:** Controlled dynamically via `FusionConfig` and `FUSION_ENABLE_*` environment variables.
- **Compatibility Matrix:** Runtime verification via `fusion_api_compat` and health checks via `fusion_health`.

