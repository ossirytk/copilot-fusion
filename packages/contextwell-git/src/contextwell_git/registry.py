"""Git and Jujutsu (jj) tool registration for copilot-fusion."""

from __future__ import annotations

from fastmcp import FastMCP

from contextwell_git.detection import detect_vcs_backend, is_jj_available
from contextwell_git.jj_adapter import (
    jj_branch,
    jj_commit,
    jj_diff,
    jj_fetch,
    jj_log,
    jj_merge,
    jj_pull,
    jj_push,
    jj_remote,
    jj_reset,
    jj_show,
    jj_stash,
    jj_status,
    jj_tag,
)
from contextwell_git.runner import err_payload, ok_payload, run_gh, run_git

_VALID_MODES = {"soft", "mixed", "hard", "merge", "keep"}


def git_status(path: str = ".") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_status(path)
    result = run_git(["status", "--short", "--branch"], path)
    if "error" in result:
        return result
    return ok_payload(path=result["cwd"], status=str(result["stdout"]).strip(), backend="git")


def git_diff(path: str = ".", staged: bool = False, file: str = "") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_diff(path=path, staged=staged, file=file)
    args = ["diff"]
    if staged:
        args.append("--staged")
    if file:
        args.extend(["--", file])
    result = run_git(args, path)
    if "error" in result:
        return result
    return ok_payload(path=result["cwd"], diff=result["stdout"], backend="git")


def git_commit(message: str, path: str = ".", add_all: bool = False) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_commit(message=message, path=path, add_all=add_all)
    if add_all:
        staged = run_git(["add", "-A"], path)
        if "error" in staged:
            return staged
    result = run_git(["commit", "-m", message], path)
    if "error" in result:
        return result
    return ok_payload(path=result["cwd"], output=str(result["stdout"]).strip(), backend="git")


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
    effective_path = repo_path or path
    if detect_vcs_backend(effective_path) == "jj":
        return jj_log(
            path=path,
            limit=limit,
            oneline=oneline,
            branch=branch,
            author=author,
            file=file,
            include_diff_stat=include_diff_stat,
            repo_path=repo_path,
            max_results=max_results,
            path_filter=path_filter,
        )
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
    result = run_git(args, effective_path)
    if "error" in result:
        return result
    raw = str(result["stdout"]).strip()
    return ok_payload(path=result["cwd"], raw=raw, backend="git", truncated=effective_limit > 500)


def git_show(ref: str = "HEAD", path: str = ".") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_show(ref=ref, path=path)
    result = run_git(["show", "--stat", "--patch", ref], path)
    if "error" in result:
        return result
    return ok_payload(path=result["cwd"], show=result["stdout"], backend="git")


def git_branch(
    path: str = ".",
    create: str | None = None,
    switch: str | None = None,
    delete: str | None = None,
    remote: bool = False,
) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_branch(path=path, create=create, switch=switch, delete=delete, remote=remote)
    if create:
        return run_git(["switch", "-c", create], path)
    if switch:
        return run_git(["switch", switch], path)
    if delete:
        return run_git(["branch", "-d", delete], path)
    args = ["branch"]
    if remote:
        args.append("-a")
    result = run_git(args, path)
    if "error" in result:
        return result
    branches = [line.strip() for line in str(result["stdout"]).splitlines() if line.strip()]
    return ok_payload(path=result["cwd"], branches=branches, backend="git")


def git_merge(branch: str, path: str = ".", no_ff: bool = False, message: str = "") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_merge(branch=branch, path=path, no_ff=no_ff, message=message)
    args = ["merge"]
    if no_ff:
        args.append("--no-ff")
    if message:
        args.extend(["-m", message])
    args.append(branch)
    return run_git(args, path)


def git_stash(path: str = ".", pop: bool = False, message: str = "") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_stash(path=path, pop=pop, message=message)
    if pop:
        return run_git(["stash", "pop"], path)
    args = ["stash", "push"]
    if message:
        args.extend(["-m", message])
    return run_git(args, path)


def git_reset(
    path: str = ".",
    ref: str = "HEAD",
    mode: str = "mixed",
    files: list[str] | None = None,
) -> dict[str, object]:
    if mode not in _VALID_MODES:
        return err_payload(f"Invalid mode {mode!r}. Must be one of: {', '.join(sorted(_VALID_MODES))}")
    if detect_vcs_backend(path) == "jj":
        return jj_reset(path=path, ref=ref, mode=mode, files=files)
    if files:
        return run_git(["reset", ref, "--", *files], path)
    return run_git(["reset", f"--{mode}", ref], path)


def git_tag(
    path: str = ".",
    create: str = "",
    delete: str = "",
    ref: str = "HEAD",
    message: str = "",
) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_tag(path=path, create=create, delete=delete, ref=ref, message=message)
    if create:
        args = ["tag"]
        if message:
            args.extend(["-a", create, "-m", message, ref])
        else:
            args.extend([create, ref])
        return run_git(args, path)
    if delete:
        return run_git(["tag", "-d", delete], path)
    result = run_git(["tag", "--list"], path)
    if "error" in result:
        return result
    return ok_payload(
        path=result["cwd"],
        tags=[line for line in str(result["stdout"]).splitlines() if line],
        backend="git",
    )


def git_remote(path: str = ".", add_name: str = "", add_url: str = "", remove: str = "") -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_remote(path=path, add_name=add_name, add_url=add_url, remove=remove)
    if add_name:
        return run_git(["remote", "add", add_name, add_url], path)
    if remove:
        return run_git(["remote", "remove", remove], path)
    result = run_git(["remote", "-v"], path)
    if "error" in result:
        return result
    return ok_payload(path=result["cwd"], remotes=str(result["stdout"]).strip(), backend="git")


def git_fetch(path: str = ".", remote: str = "origin", prune: bool = False) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_fetch(path=path, remote=remote, prune=prune)
    args = ["fetch", remote]
    if prune:
        args.append("--prune")
    return run_git(args, path)


def git_pull(path: str = ".", remote: str = "origin", branch: str = "", rebase: bool = False) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_pull(path=path, remote=remote, branch=branch, rebase=rebase)
    args = ["pull", remote]
    if branch:
        args.append(branch)
    if rebase:
        args.append("--rebase")
    return run_git(args, path)


def git_push(
    path: str = ".",
    remote: str = "origin",
    branch: str = "",
    force: bool = False,
    set_upstream: bool = False,
    tags: bool = False,
) -> dict[str, object]:
    if detect_vcs_backend(path) == "jj":
        return jj_push(
            path=path,
            remote=remote,
            branch=branch,
            force=force,
            set_upstream=set_upstream,
            tags=tags,
        )
    args = ["push", remote]
    if branch:
        args.append(branch)
    if force:
        args.append("--force-with-lease")
    if set_upstream:
        args.append("-u")
    if tags:
        args.append("--tags")
    return run_git(args, path)


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
    return run_gh(args, path)


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
    return run_gh(args, path)


def gh_pr_view(pr: str, path: str = ".") -> dict[str, object]:
    return run_gh(["pr", "view", pr], path)


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
    return run_gh(args, path)


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
    return run_gh(args, path)


def gh_issue_view(issue: str, path: str = ".") -> dict[str, object]:
    return run_gh(["issue", "view", issue], path)


def fusion_git_health() -> dict[str, object]:
    jj_avail = is_jj_available()
    return {
        "domain": "git",
        "status": "ready",
        "jj_available": jj_avail,
        "default_backend": "jj" if jj_avail else "git",
    }


def register(mcp: FastMCP) -> None:
    """Register contextwell-git tools into the provided MCP server."""
    mcp.tool(git_status)
    mcp.tool(git_diff)
    mcp.tool(git_commit)
    mcp.tool(git_log)
    mcp.tool(git_show)
    mcp.tool(git_branch)
    mcp.tool(git_merge)
    mcp.tool(git_stash)
    mcp.tool(git_reset)
    mcp.tool(git_tag)
    mcp.tool(git_remote)
    mcp.tool(git_fetch)
    mcp.tool(git_pull)
    mcp.tool(git_push)
    mcp.tool(gh_pr_create)
    mcp.tool(gh_pr_list)
    mcp.tool(gh_pr_view)
    mcp.tool(gh_issue_create)
    mcp.tool(gh_issue_list)
    mcp.tool(gh_issue_view)
    mcp.tool(name="fusion_git_health")(fusion_git_health)
