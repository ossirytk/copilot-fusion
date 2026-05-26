"""Unified MCP server entry point for copilot-fusion."""

from copilot_fusion.api_compat import build_matrix
from contextwell_core import register as register_core
from contextwell_diff import register as register_diff
from contextwell_git import register as register_git
from contextwell_tools import register as register_tools
from copilot_fusion_shared import FusionConfig
from fastmcp import FastMCP


def create_server(config: FusionConfig | None = None) -> FastMCP:
    """Create and configure the unified MCP server."""

    effective_config = config or FusionConfig.from_env()
    mcp = FastMCP(name="copilot-fusion")

    if effective_config.enable_core:
        register_core(mcp)
    if effective_config.enable_git:
        register_git(mcp)
    if effective_config.enable_tools:
        register_tools(mcp)
    if effective_config.enable_diff:
        register_diff(mcp)

    @mcp.tool(name="fusion_health")
    def fusion_health() -> dict[str, object]:
        return {
            "server": "copilot-fusion",
            "status": "ready",
            "domains": {
                "core": effective_config.enable_core,
                "git": effective_config.enable_git,
                "tools": effective_config.enable_tools,
                "diff": effective_config.enable_diff,
            },
        }

    @mcp.tool(name="fusion_api_compat")
    async def fusion_api_compat() -> dict[str, object]:
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        return build_matrix(names)

    return mcp


def run() -> None:
    """Run the unified MCP server."""

    create_server().run()
