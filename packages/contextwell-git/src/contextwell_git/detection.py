"""VCS backend detection helpers (Git vs Jujutsu)."""

from __future__ import annotations

import shutil
from pathlib import Path

from copilot_fusion_shared import resolve_path


def is_jj_available() -> bool:
    """Return True if the `jj` executable is found in PATH."""
    return shutil.which("jj") is not None


def find_jj_root(path: str | Path = ".") -> Path | None:
    """Search upwards from path for a .jj repository directory."""
    current = resolve_path(path)
    for candidate in [current, *current.parents]:
        if (candidate / ".jj").is_dir():
            return candidate
    return None


def find_git_root(path: str | Path = ".") -> Path | None:
    """Search upwards from path for a .git repository directory or file."""
    current = resolve_path(path)
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def detect_vcs_backend(path: str | Path = ".") -> str:
    """Detect whether to use 'jj' or 'git' backend for the given path.

    Returns:
        'jj' if jj binary is available and a .jj workspace is found.
        'git' otherwise.
    """
    if is_jj_available() and find_jj_root(path) is not None:
        return "jj"
    return "git"
