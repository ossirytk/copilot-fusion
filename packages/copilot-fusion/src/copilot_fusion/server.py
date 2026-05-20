"""Unified MCP server entry point for copilot-fusion."""

from contextwell_core import register as register_core
from contextwell_git import register as register_git
from contextwell_tools import register as register_tools
from copilot_fusion_shared import FusionConfig
from fastmcp import FastMCP


def create_server(config: FusionConfig | None = None) -> FastMCP:
    """Create and configure the unified MCP server."""

    effective_config = config or FusionConfig()
    mcp = FastMCP(name="copilot-fusion")

    if effective_config.enable_core:
        register_core(mcp)
    if effective_config.enable_git:
        register_git(mcp)
    if effective_config.enable_tools:
        register_tools(mcp)

    @mcp.tool(name="fusion_health")
    def fusion_health() -> dict[str, object]:
        return {
            "server": "copilot-fusion",
            "status": "ready",
            "domains": {
                "core": effective_config.enable_core,
                "git": effective_config.enable_git,
                "tools": effective_config.enable_tools,
            },
        }

    return mcp


def run() -> None:
    """Run the unified MCP server."""

    create_server().run()

