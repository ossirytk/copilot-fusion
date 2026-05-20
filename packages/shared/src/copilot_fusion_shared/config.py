"""Shared configuration model for package registration toggles."""

from dataclasses import dataclass


@dataclass(slots=True)
class FusionConfig:
    """Controls which domains are registered into the unified MCP server."""

    enable_core: bool = True
    enable_git: bool = True
    enable_tools: bool = True

