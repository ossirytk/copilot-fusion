"""Shared package for copilot-fusion."""

from copilot_fusion_shared.commands import CommandResult, run_command
from copilot_fusion_shared.config import FusionConfig
from copilot_fusion_shared.paths import app_data_dir, resolve_path

__all__ = ["CommandResult", "FusionConfig", "app_data_dir", "resolve_path", "run_command"]
