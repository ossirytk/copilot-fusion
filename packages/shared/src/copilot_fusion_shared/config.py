"""Shared configuration model for package registration toggles."""

import os
from dataclasses import dataclass


@dataclass(slots=True)
class FusionConfig:
    """Controls which domains are registered into the unified MCP server."""

    enable_core: bool = True
    enable_git: bool = True
    enable_tools: bool = True

    @classmethod
    def from_env(cls) -> "FusionConfig":
        """Load config from environment variables."""

        return cls(
            enable_core=_env_bool("FUSION_ENABLE_CORE", True),
            enable_git=_env_bool("FUSION_ENABLE_GIT", True),
            enable_tools=_env_bool("FUSION_ENABLE_TOOLS", True),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
