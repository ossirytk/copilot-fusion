"""Subprocess execution helpers for Git, Jujutsu, and GitHub CLI."""

from __future__ import annotations

from copilot_fusion_shared import resolve_path, run_command


def ok_payload(**payload: object) -> dict[str, object]:
    return payload


def err_payload(message: str) -> dict[str, object]:
    return {"error": message}


def run_git(args: list[str], path: str = ".") -> dict[str, object]:
    """Execute a git command with structured result."""
    cwd = resolve_path(path)
    result = run_command(["git", *args], cwd)
    if not result.ok:
        return err_payload(result.stderr.strip() or f"git {' '.join(args)} failed")
    return ok_payload(cwd=str(cwd), stdout=result.stdout, stderr=result.stderr)


def run_jj(args: list[str], path: str = ".") -> dict[str, object]:
    """Execute a jj command with structured result."""
    cwd = resolve_path(path)
    result = run_command(["jj", "--no-pager", "--color=never", *args], cwd)
    if not result.ok:
        return err_payload(result.stderr.strip() or f"jj {' '.join(args)} failed")
    return ok_payload(cwd=str(cwd), stdout=result.stdout, stderr=result.stderr)


def run_gh(args: list[str], path: str = ".") -> dict[str, object]:
    """Execute a gh command with structured result."""
    cwd = resolve_path(path)
    result = run_command(["gh", *args], cwd)
    if not result.ok:
        return err_payload(result.stderr.strip() or f"gh {' '.join(args)} failed")
    return ok_payload(cwd=str(cwd), stdout=result.stdout, stderr=result.stderr)
