"""Shared configuration model for package registration toggles."""

import os
from dataclasses import dataclass


@dataclass(slots=True)
class FusionConfig:
    """Controls which domains are registered into the unified MCP server."""

    enable_core: bool = True
    enable_git: bool = True
    enable_tools: bool = True
    enable_diff: bool = True
    profile: str = "full"  # "core": memory + symbol_search only; "full": also the portable file/git/diff/terminal tools

    @classmethod
    def from_env(cls) -> "FusionConfig":
        """Load config from environment variables."""

        return cls(
            enable_core=_env_bool("FUSION_ENABLE_CORE", True),
            enable_git=_env_bool("FUSION_ENABLE_GIT", True),
            enable_tools=_env_bool("FUSION_ENABLE_TOOLS", True),
            enable_diff=_env_bool("FUSION_ENABLE_DIFF", True),
            profile=_env_profile(),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_profile() -> str:
    value = os.getenv("FUSION_PROFILE", "full").strip().lower() or "full"
    if value not in {"core", "full"}:
        raise ValueError(f"FUSION_PROFILE must be 'core' or 'full', got {value!r}")
    return value
