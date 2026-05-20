"""Tool registration entry point for the tooling domain."""

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register contextwell-tools tools into the provided MCP server."""

    @mcp.tool(name="fusion_tools_health")
    def fusion_tools_health() -> dict[str, str]:
        return {"domain": "tools", "status": "ready"}

