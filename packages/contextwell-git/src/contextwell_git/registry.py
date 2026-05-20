"""Tool registration entry point for the git domain."""

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register contextwell-git tools into the provided MCP server."""

    @mcp.tool(name="fusion_git_health")
    def fusion_git_health() -> dict[str, str]:
        return {"domain": "git", "status": "ready"}

