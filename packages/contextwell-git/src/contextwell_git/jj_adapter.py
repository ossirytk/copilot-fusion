"""Jujutsu (jj) VCS adapter for colocated repositories."""

from __future__ import annotations

from contextwell_git.runner import err_payload, ok_payload, run_git, run_jj

_VALID_MODES = {"soft", "mixed", "hard", "merge", "keep"}


def jj_status(path: str = ".") -> dict[str, object]:
    """Execute status using Jujutsu with change metadata."""
    status_res = run_jj(["status"], path)
    if "error" in status_res:
        return status_res

    info_res = run_jj(
        [
            "log",
            "-r",
            "@",
            "--no-graph",
            "-T",
            'change_id ++ "\x1f" ++ commit_id ++ "\x1f" ++ empty ++ "\x1f" ++ conflict ++ "\x1f" ++ description.first_line()',
        ],
        path,
    )

    change_id = ""
    commit_id = ""
    is_empty = False
    is_conflicted = False
    description = ""

    if "error" not in info_res and info_res.get("stdout"):
        parts = str(info_res["stdout"]).split("\x1f")
        if len(parts) >= 5:
            change_id = parts[0].strip()
            commit_id = parts[1].strip()
            is_empty = parts[2].strip().lower() == "true"
            is_conflicted = parts[3].strip().lower() == "true"
            description = parts[4].strip()

    return ok_payload(
        path=status_res["cwd"],
        status=str(status_res["stdout"]).strip(),
        backend="jj",
        change_id=change_id,
        commit_id=commit_id,
        is_empty=is_empty,
        is_conflicted=is_conflicted,
        description=description,
    )


def jj_diff(path: str = ".", staged: bool = False, file: str = "") -> dict[str, object]:
    """Execute diff using Jujutsu."""
    args = ["diff"]
    if file:
        args.extend(["--", file])
    res = run_jj(args, path)
    if "error" in res:
        return res
    return ok_payload(path=res["cwd"], diff=res["stdout"], backend="jj")


def jj_commit(message: str, path: str = ".", add_all: bool = False) -> dict[str, object]:
    """Execute commit using Jujutsu."""
    res = run_jj(["commit", "-m", message], path)
    if "error" in res:
        return res
    return ok_payload(path=res["cwd"], output=str(res["stdout"]).strip(), backend="jj")


def jj_log(
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
    """Execute commit / revision log using Jujutsu."""
    effective_path = repo_path or path
    effective_limit = max_results if repo_path else limit
    effective_file = path_filter or file
    capped_limit = max(1, min(effective_limit, 500))

    args = ["log", "--no-graph", f"-n{capped_limit}"]
    if oneline:
        args.extend(
            ["-T", 'change_id.shortest() ++ " " ++ commit_id.shortest() ++ " " ++ description.first_line() ++ "\n"']
        )
    else:
        args.extend(
            [
                "-T",
                'commit_id ++ "\x1f" ++ author.name() ++ "\x1f" ++ author.email() ++ "\x1f" ++ author.timestamp() ++ "\x1f" ++ description ++ "\n"',
            ]
        )

    if author and branch:
        args.extend(["-r", f"ancestors({branch}) & author({author})"])
    elif branch:
        args.extend(["-r", f"ancestors({branch})"])
    elif author:
        args.extend(["-r", f"author({author})"])

    if include_diff_stat:
        args.append("--stat")
    if effective_file:
        args.extend(["--", effective_file])

    res = run_jj(args, effective_path)
    if "error" in res:
        return res
    raw = str(res["stdout"]).strip()
    return ok_payload(path=res["cwd"], raw=raw, backend="jj", truncated=effective_limit > 500)


def jj_show(ref: str = "HEAD", path: str = ".") -> dict[str, object]:
    """Execute show for revision using Jujutsu."""
    if ref == "HEAD":
        target = "@-"
    else:
        target = ref

    res = run_jj(["show", target], path)
    if "error" in res:
        return res
    return ok_payload(path=res["cwd"], show=res["stdout"], backend="jj")


def jj_branch(
    path: str = ".",
    create: str | None = None,
    switch: str | None = None,
    delete: str | None = None,
    remote: bool = False,
) -> dict[str, object]:
    """Manage branches (bookmarks) using Jujutsu."""
    if create:
        log_res = run_jj(["log", "-r", "@", "--no-graph", "-T", "empty"], path)
        target = "@-" if ("error" not in log_res and str(log_res.get("stdout", "")).strip() == "true") else "@"
        return run_jj(["bookmark", "create", create, "-r", target], path)
    if switch:
        return run_jj(["edit", switch], path)
    if delete:
        return run_jj(["bookmark", "delete", delete], path)

    args = ["bookmark", "list", "-T", 'name ++ "\n"']
    if remote:
        args.insert(2, "-a")
    res = run_jj(args, path)
    if "error" in res:
        return res
    branches = [line.strip() for line in str(res["stdout"]).splitlines() if line.strip()]
    return ok_payload(path=res["cwd"], branches=branches, backend="jj")


def jj_merge(branch: str, path: str = ".", no_ff: bool = False, message: str = "") -> dict[str, object]:
    """Merge branch using Jujutsu."""
    log_res = run_jj(["log", "-r", "@", "--no-graph", "-T", "empty"], path)
    current = "@-" if ("error" not in log_res and str(log_res.get("stdout", "")).strip() == "true") else "@"
    res = run_jj(["new", current, branch], path)
    if "error" in res:
        return res
    if message:
        run_jj(["describe", "-m", message], path)
    return ok_payload(path=res["cwd"], backend="jj", stdout=res.get("stdout", ""), stderr=res.get("stderr", ""))


def jj_stash(path: str = ".", pop: bool = False, message: str = "") -> dict[str, object]:
    """Push or pop stash using Jujutsu or Git fallback."""
    if pop:
        res = run_jj(["squash", "--from", "@-", "--to", "@"], path)
        if "error" in res:
            return run_git(["stash", "pop"], path)
        return ok_payload(path=res["cwd"], backend="jj", stdout=res.get("stdout", ""), stderr=res.get("stderr", ""))

    msg = message or "stash"
    res_desc = run_jj(["describe", "-m", f"stash: {msg}"], path)
    if "error" in res_desc:
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        return run_git(args, path)
    res_new = run_jj(["new", "@-"], path)
    if "error" in res_new:
        return res_new
    return ok_payload(
        path=res_new["cwd"], backend="jj", stdout=res_new.get("stdout", ""), stderr=res_new.get("stderr", "")
    )


def jj_reset(
    path: str = ".",
    ref: str = "HEAD",
    mode: str = "mixed",
    files: list[str] | None = None,
) -> dict[str, object]:
    """Reset changes using Jujutsu restore."""
    if mode not in _VALID_MODES:
        return err_payload(f"Invalid mode {mode!r}. Must be one of: {', '.join(sorted(_VALID_MODES))}")
    target = "@-" if ref == "HEAD" else ref
    if files:
        return run_jj(["restore", "--from", target, "--", *files], path)
    return run_jj(["restore", "--from", target], path)


def jj_tag(
    path: str = ".",
    create: str = "",
    delete: str = "",
    ref: str = "HEAD",
    message: str = "",
) -> dict[str, object]:
    """Manage tags using Jujutsu."""
    target = "@-" if ref == "HEAD" else ref
    if create:
        if message:
            return run_git(["tag", "-a", create, "-m", message, ref], path)
        return run_jj(["tag", "set", create, "-r", target], path)
    if delete:
        return run_jj(["tag", "delete", delete], path)
    res = run_jj(["tag", "list"], path)
    if "error" in res:
        return res
    tags = [line.strip() for line in str(res["stdout"]).splitlines() if line.strip()]
    return ok_payload(path=res["cwd"], tags=tags, backend="jj")


def jj_remote(path: str = ".", add_name: str = "", add_url: str = "", remove: str = "") -> dict[str, object]:
    """Manage Git remotes via Jujutsu."""
    if add_name and add_url:
        return run_jj(["git", "remote", "add", add_name, add_url], path)
    if remove:
        return run_jj(["git", "remote", "remove", remove], path)
    res = run_jj(["git", "remote", "list"], path)
    if "error" in res:
        return res
    return ok_payload(path=res["cwd"], remotes=str(res["stdout"]).strip(), backend="jj")


def jj_fetch(path: str = ".", remote: str = "origin", prune: bool = False) -> dict[str, object]:
    """Fetch from remote via Jujutsu."""
    args = ["git", "fetch", "--remote", remote]
    return run_jj(args, path)


def jj_pull(path: str = ".", remote: str = "origin", branch: str = "", rebase: bool = False) -> dict[str, object]:
    """Pull from remote and import into Jujutsu."""
    args = ["git", "fetch", "--remote", remote]
    res = run_jj(args, path)
    if "error" in res:
        return res
    import_res = run_jj(["git", "import"], path)
    if "error" in import_res:
        return import_res
    return res


def jj_push(
    path: str = ".",
    remote: str = "origin",
    branch: str = "",
    force: bool = False,
    set_upstream: bool = False,
    tags: bool = False,
) -> dict[str, object]:
    """Push to remote via Jujutsu."""
    args = ["git", "push", "--remote", remote]
    if branch:
        args.extend(["--bookmark", branch])
    if tags:
        args.append("--all")
    return run_jj(args, path)
