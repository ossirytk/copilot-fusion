"""Tools domain registration for copilot-fusion."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


_REQUESTS = Counter()


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _project(node: Any, field: str) -> Any:
    current: Any = node
    for part in field.split("."):
        if isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                return None
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def register(mcp: FastMCP) -> None:
    """Register contextwell-tools tools into the provided MCP server."""

    @mcp.tool
    def fs_glob(base_path: str, patterns: list[str], max_results: int = 5000) -> dict[str, object]:
        _REQUESTS["fs_glob"] += 1
        root = _resolve(base_path)
        matches: list[str] = []
        for pattern in patterns:
            for match in root.glob(pattern):
                matches.append(str(match))
                if len(matches) >= max_results:
                    return {"results": sorted(set(matches)), "truncated": True}
        return {"results": sorted(set(matches)), "truncated": False}

    @mcp.tool
    def fs_tree(
        path: str,
        include_hidden: bool = False,
        max_depth: int = 3,
        max_entries: int = 2000,
    ) -> dict[str, object]:
        _REQUESTS["fs_tree"] += 1
        root = _resolve(path)
        entries: list[dict[str, object]] = []
        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue and len(entries) < max_entries:
            current, depth = queue.pop(0)
            if depth > max_depth:
                continue
            for child in sorted(current.iterdir(), key=lambda p: p.name):
                if not include_hidden and child.name.startswith("."):
                    continue
                rel = str(child.relative_to(root))
                item = {"path": rel if rel != "." else ".", "type": "dir" if child.is_dir() else "file", "depth": depth}
                entries.append(item)
                if len(entries) >= max_entries:
                    break
                if child.is_dir():
                    queue.append((child, depth + 1))
        return {"root": str(root), "entries": entries, "truncated": len(entries) >= max_entries}

    @mcp.tool
    def text_search(
        mode: str,
        paths: list[str],
        query: str,
        case_sensitive: bool = False,
        max_results: int = 5000,
    ) -> dict[str, object]:
        _REQUESTS["text_search"] += 1
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query if mode == "regex" else re.escape(query), flags)
        results: list[dict[str, object]] = []
        for p in paths:
            file_path = _resolve(p)
            if file_path.is_dir():
                candidates = [x for x in file_path.rglob("*") if x.is_file()]
            else:
                candidates = [file_path]
            for candidate in candidates:
                try:
                    text = candidate.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    for match in pattern.finditer(line):
                        results.append(
                            {
                                "path": str(candidate),
                                "line": line_no,
                                "start": match.start(),
                                "end": match.end(),
                                "text": line,
                            }
                        )
                        if len(results) >= max_results:
                            return {"results": results, "truncated": True}
        return {"results": results, "truncated": False}

    @mcp.tool
    def json_select(
        path: str,
        fields: list[str],
        filters: list[dict[str, object]] | None = None,
        max_results: int = 5000,
    ) -> dict[str, object]:
        _REQUESTS["json_select"] += 1
        data = json.loads(_resolve(path).read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else [data]
        selected: list[dict[str, object]] = []
        for row in rows:
            if filters:
                passed = True
                for filt in filters:
                    value = _project(row, str(filt["field"]))
                    op = str(filt["op"])
                    expected = filt["value"]
                    if op == "eq" and value != expected:
                        passed = False
                        break
                    if op == "contains" and str(expected) not in str(value):
                        passed = False
                        break
                if not passed:
                    continue
            selected.append({field: _project(row, field) for field in fields})
            if len(selected) >= max_results:
                return {"results": selected, "truncated": True}
        return {"results": selected, "truncated": False}

    @mcp.tool
    def yaml_select(path: str, fields: list[str]) -> dict[str, object]:
        _REQUESTS["yaml_select"] += 1
        resolved = _resolve(path)
        suffix = resolved.suffix.lower()
        if suffix == ".toml":
            if tomllib is None:
                return {"error": "tomllib unavailable in this Python runtime"}
            data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        else:
            if yaml is None:
                return {"error": "pyyaml not installed"}
            data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
        return {"results": {field: _project(data, field) for field in fields}}

    @mcp.tool
    def git_log(repo_path: str, max_results: int = 100, path_filter: str = "", include_diff_stat: bool = False) -> dict[str, object]:
        _REQUESTS["git_log"] += 1
        cwd = str(_resolve(repo_path))
        fmt = "%H%x1f%an%x1f%ad%x1f%s"
        cmd = ["git", "log", f"-n{max(1, min(max_results, 500))}", f"--pretty=format:{fmt}"]
        if include_diff_stat:
            cmd.append("--name-only")
        if path_filter:
            cmd.extend(["--", path_filter])
        try:
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
        except OSError as exc:
            return {"error": str(exc)}
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "git log failed"}
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        commits: list[dict[str, object]] = []
        for line in lines:
            if "\x1f" not in line:
                continue
            sha, author, date, subject = line.split("\x1f", maxsplit=3)
            commits.append({"sha": sha, "author": author, "date": date, "subject": subject})
        return {"repo_path": cwd, "commits": commits, "truncated": max_results > 500}

    @mcp.tool
    def server_stats() -> dict[str, object]:
        _REQUESTS["server_stats"] += 1
        return {"requests": dict(_REQUESTS)}

    @mcp.tool(name="fusion_tools_health")
    def fusion_tools_health() -> dict[str, str]:
        _REQUESTS["fusion_tools_health"] += 1
        return {"domain": "tools", "status": "ready"}
