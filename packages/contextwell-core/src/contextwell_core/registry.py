"""Tool registration entry point for the core memory domain."""

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register contextwell-core tools into the provided MCP server."""

    @mcp.tool(name="fusion_core_health")
    def fusion_core_health() -> dict[str, str]:
        return {"domain": "core", "status": "ready"}

