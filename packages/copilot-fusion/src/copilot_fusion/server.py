"""Unified MCP server entry point for copilot-fusion."""

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
    core_profile = effective_config.profile == "core"
    if effective_config.enable_git and not core_profile:
        register_git(mcp)
    if effective_config.enable_tools:
        register_tools(mcp, core_only=core_profile)
    if effective_config.enable_diff and not core_profile:
        register_diff(mcp)

    @mcp.tool(name="fusion_health")
    def fusion_health() -> dict[str, object]:
        return {
            "server": "copilot-fusion",
            "status": "ready",
            "profile": effective_config.profile,
            "domains": {
                "core": effective_config.enable_core,
                "git": effective_config.enable_git,
                "tools": effective_config.enable_tools,
                "diff": effective_config.enable_diff,
            },
        }

    return mcp


def run() -> None:
    """Run the unified MCP server."""

    create_server().run()
