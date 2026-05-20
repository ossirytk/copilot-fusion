"""Git tool registration for copilot-fusion.

This is an initial migration from gitpilot focused on preserving tool names and
high-utility behavior.
"""

from __future__ import annotations

from fastmcp import FastMCP
from copilot_fusion_shared import resolve_path, run_command


def _ok(**payload: object) -> dict[str, object]:
    return payload


def _err(message: str) -> dict[str, object]:
    return {"error": message}


def _run_git(args: list[str], path: str = ".") -> dict[str, object]:
    cwd = resolve_path(path)
    result = run_command(["git", *args], cwd)
    if not result.ok:
        return _err(result.stderr.strip() or f"git {' '.join(args)} failed")
    return _ok(cwd=str(cwd), stdout=result.stdout, stderr=result.stderr)


def _run_gh(args: list[str], path: str = ".") -> dict[str, object]:
    cwd = resolve_path(path)
    result = run_command(["gh", *args], cwd)
    if not result.ok:
        return _err(result.stderr.strip() or f"gh {' '.join(args)} failed")
    return _ok(cwd=str(cwd), stdout=result.stdout, stderr=result.stderr)


def register(mcp: FastMCP) -> None:
    """Register contextwell-git tools into the provided MCP server."""

    @mcp.tool
    def git_status(path: str = ".") -> dict[str, object]:
        result = _run_git(["status", "--short", "--branch"], path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], status=str(result["stdout"]).strip())

    @mcp.tool
    def git_diff(path: str = ".", staged: bool = False, file: str = "") -> dict[str, object]:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file:
            args.extend(["--", file])
        result = _run_git(args, path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], diff=result["stdout"])

    @mcp.tool
    def git_commit(message: str, path: str = ".", add_all: bool = False) -> dict[str, object]:
        if add_all:
            staged = _run_git(["add", "-A"], path)
            if "error" in staged:
                return staged
        result = _run_git(["commit", "-m", message], path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], output=str(result["stdout"]).strip())

    @mcp.tool
    def git_log(
        path: str = ".",
        limit: int = 20,
        oneline: bool = True,
        branch: str = "",
        author: str = "",
        file: str = "",
        include_diff_stat: bool = False,
        repo_path: str = "",
        max_results: int = 100,
        path_filter: str = "",
    ) -> dict[str, object]:
        # Compatibility bridge: accept toolpilot-style parameters as well.
        effective_path = repo_path or path
        effective_limit = max_results if repo_path else limit
        effective_file = path_filter or file
        fmt = "%h %s" if oneline else "%H%x1f%an%x1f%ae%x1f%ad%x1f%s"
        args = ["log", f"-n{max(1, min(effective_limit, 500))}", f"--pretty=format:{fmt}"]
        if author:
            args.append(f"--author={author}")
        target = branch or "HEAD"
        args.append(target)
        if include_diff_stat:
            args.append("--name-only")
        if effective_file:
            args.extend(["--", effective_file])
        result = _run_git(args, effective_path)
        if "error" in result:
            return result
        raw = str(result["stdout"]).strip()
        return _ok(path=result["cwd"], raw=raw, truncated=effective_limit > 500)

    @mcp.tool
    def git_show(ref: str = "HEAD", path: str = ".") -> dict[str, object]:
        result = _run_git(["show", "--stat", "--patch", ref], path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], show=result["stdout"])

    @mcp.tool
    def git_branch(
        path: str = ".",
        create: str | None = None,
        switch: str | None = None,
        delete: str | None = None,
        remote: bool = False,
    ) -> dict[str, object]:
        if create:
            return _run_git(["switch", "-c", create], path)
        if switch:
            return _run_git(["switch", switch], path)
        if delete:
            return _run_git(["branch", "-d", delete], path)
        args = ["branch"]
        if remote:
            args.append("-a")
        result = _run_git(args, path)
        if "error" in result:
            return result
        branches = [line.strip() for line in str(result["stdout"]).splitlines() if line.strip()]
        return _ok(path=result["cwd"], branches=branches)

    @mcp.tool
    def git_merge(branch: str, path: str = ".", no_ff: bool = False, message: str = "") -> dict[str, object]:
        args = ["merge"]
        if no_ff:
            args.append("--no-ff")
        if message:
            args.extend(["-m", message])
        args.append(branch)
        return _run_git(args, path)

    @mcp.tool
    def git_stash(path: str = ".", pop: bool = False, message: str = "") -> dict[str, object]:
        if pop:
            return _run_git(["stash", "pop"], path)
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        return _run_git(args, path)

    @mcp.tool
    def git_reset(
        path: str = ".",
        ref: str = "HEAD",
        mode: str = "mixed",
        files: list[str] | None = None,
    ) -> dict[str, object]:
        if files:
            return _run_git(["reset", "HEAD", *files], path)
        return _run_git(["reset", f"--{mode}", ref], path)

    @mcp.tool
    def git_tag(
        path: str = ".",
        create: str = "",
        delete: str = "",
        ref: str = "HEAD",
        message: str = "",
    ) -> dict[str, object]:
        if create:
            args = ["tag"]
            if message:
                args.extend(["-a", create, "-m", message, ref])
            else:
                args.extend([create, ref])
            return _run_git(args, path)
        if delete:
            return _run_git(["tag", "-d", delete], path)
        result = _run_git(["tag", "--list"], path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], tags=[line for line in str(result["stdout"]).splitlines() if line])

    @mcp.tool
    def git_remote(path: str = ".", add_name: str = "", add_url: str = "", remove: str = "") -> dict[str, object]:
        if add_name:
            return _run_git(["remote", "add", add_name, add_url], path)
        if remove:
            return _run_git(["remote", "remove", remove], path)
        result = _run_git(["remote", "-v"], path)
        if "error" in result:
            return result
        return _ok(path=result["cwd"], remotes=str(result["stdout"]).strip())

    @mcp.tool
    def git_fetch(path: str = ".", remote: str = "origin", prune: bool = False) -> dict[str, object]:
        args = ["fetch", remote]
        if prune:
            args.append("--prune")
        return _run_git(args, path)

    @mcp.tool
    def git_pull(path: str = ".", remote: str = "origin", branch: str = "", rebase: bool = False) -> dict[str, object]:
        args = ["pull", remote]
        if branch:
            args.append(branch)
        if rebase:
            args.append("--rebase")
        return _run_git(args, path)

    @mcp.tool
    def git_push(
        path: str = ".",
        remote: str = "origin",
        branch: str = "",
        force: bool = False,
        set_upstream: bool = False,
        tags: bool = False,
    ) -> dict[str, object]:
        args = ["push", remote]
        if branch:
            args.append(branch)
        if force:
            args.append("--force-with-lease")
        if set_upstream:
            args.append("-u")
        if tags:
            args.append("--tags")
        return _run_git(args, path)

    @mcp.tool
    def gh_pr_create(
        title: str,
        body: str = "",
        base: str = "main",
        draft: bool = False,
        path: str = ".",
    ) -> dict[str, object]:
        args = ["pr", "create", "--title", title, "--base", base]
        if body:
            args.extend(["--body", body])
        if draft:
            args.append("--draft")
        return _run_gh(args, path)

    @mcp.tool
    def gh_pr_list(
        path: str = ".",
        state: str = "open",
        limit: int = 30,
        base: str = "",
        author: str = "",
        label: str = "",
    ) -> dict[str, object]:
        args = ["pr", "list", "--state", state, "--limit", str(max(1, limit))]
        if base:
            args.extend(["--base", base])
        if author:
            args.extend(["--author", author])
        if label:
            args.extend(["--label", label])
        return _run_gh(args, path)

    @mcp.tool
    def gh_pr_view(pr: str, path: str = ".") -> dict[str, object]:
        return _run_gh(["pr", "view", pr], path)

    @mcp.tool
    def gh_issue_create(
        title: str,
        body: str = "",
        label: str = "",
        assignee: str = "",
        path: str = ".",
    ) -> dict[str, object]:
        args: list[str] = ["issue", "create", "--title", title]
        if body:
            args.extend(["--body", body])
        if label:
            args.extend(["--label", label])
        if assignee:
            args.extend(["--assignee", assignee])
        return _run_gh(args, path)

    @mcp.tool
    def gh_issue_list(
        path: str = ".",
        state: str = "open",
        limit: int = 30,
        label: str = "",
        assignee: str = "",
        author: str = "",
    ) -> dict[str, object]:
        args = ["issue", "list", "--state", state, "--limit", str(max(1, limit))]
        if label:
            args.extend(["--label", label])
        if assignee:
            args.extend(["--assignee", assignee])
        if author:
            args.extend(["--author", author])
        return _run_gh(args, path)

    @mcp.tool(name="fusion_git_health")
    def fusion_git_health() -> dict[str, str]:
        return {"domain": "git", "status": "ready"}
