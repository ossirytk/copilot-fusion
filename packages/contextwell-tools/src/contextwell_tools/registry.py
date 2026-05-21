"""Tools domain registration for copilot-fusion."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from copilot_fusion_shared import resolve_path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


_REQUESTS = Counter()


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
        root = resolve_path(base_path)
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
        root = resolve_path(path)
        entries: list[dict[str, object]] = []
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        while queue and len(entries) < max_entries:
            current, depth = queue.popleft()
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
        try:
            pattern = re.compile(query if mode == "regex" else re.escape(query), flags)
        except re.error as exc:
            return {"error": f"Invalid regex pattern: {exc}"}
        results: list[dict[str, object]] = []
        for p in paths:
            file_path = resolve_path(p)
            if file_path.is_dir():
                candidates = (x for x in file_path.rglob("*") if x.is_file())
            else:
                candidates = iter([file_path])
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
    def read_file(
        path: str,
        start_line: int = 1,
        end_line: int = -1,
        max_bytes: int = 200_000,
    ) -> dict[str, object]:
        _REQUESTS["read_file"] += 1
        resolved = resolve_path(path)
        file_size = resolved.stat().st_size
        with resolved.open("rb") as fh:
            data = fh.read(max_bytes if max_bytes > 0 else -1)
        truncated = max_bytes > 0 and file_size > max_bytes
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        s = max(1, start_line)
        e = len(lines) if end_line <= 0 else min(end_line, len(lines))
        if s > len(lines):
            selected: list[str] = []
        else:
            selected = lines[s - 1 : e]
        return {
            "path": str(resolved),
            "content": "\n".join(selected),
            "start_line": s,
            "end_line": e,
            "truncated": truncated,
            "bytes_read": len(data),
        }

    @mcp.tool
    def json_select(
        path: str,
        fields: list[str],
        filters: list[dict[str, object]] | None = None,
        max_results: int = 5000,
    ) -> dict[str, object]:
        _REQUESTS["json_select"] += 1
        try:
            data = json.loads(resolve_path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"error": f"Failed to read/parse JSON: {exc}"}
        rows = data if isinstance(data, list) else [data]
        selected: list[dict[str, object]] = []
        for row in rows:
            if filters:
                passed = True
                for filt in filters:
                    if not isinstance(filt, dict) or not {"field", "op", "value"}.issubset(filt):
                        return {"error": f"Filter missing required keys (field, op, value): {filt!r}"}
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
        resolved = resolve_path(path)
        suffix = resolved.suffix.lower()
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {"error": f"Failed to read file: {exc}"}
        if suffix == ".toml":
            if tomllib is None:
                return {"error": "tomllib unavailable in this Python runtime"}
            try:
                data = tomllib.loads(text)
            except ValueError as exc:
                return {"error": f"Failed to parse TOML: {exc}"}
        else:
            if yaml is None:
                return {"error": "pyyaml not installed"}
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                return {"error": f"Failed to parse YAML: {exc}"}
        return {"results": {field: _project(data, field) for field in fields}}

    @mcp.tool
    def file_hash(path: str, algorithm: str = "sha256") -> dict[str, object]:
        _REQUESTS["file_hash"] += 1
        resolved = resolve_path(path)
        normalized = algorithm.lower()
        if normalized not in {"sha256", "sha1", "md5"}:
            return {"error": f"Unsupported algorithm: {algorithm}"}
        hasher = hashlib.new(normalized)
        with resolved.open("rb") as handle:
            while True:
                chunk = handle.read(65_536)
                if not chunk:
                    break
                hasher.update(chunk)
        return {"path": str(resolved), "algorithm": normalized, "hash": hasher.hexdigest()}

    @mcp.tool
    def server_stats() -> dict[str, object]:
        _REQUESTS["server_stats"] += 1
        return {"requests": dict(_REQUESTS)}

    @mcp.tool(name="fusion_tools_health")
    def fusion_tools_health() -> dict[str, str]:
        _REQUESTS["fusion_tools_health"] += 1
        return {"domain": "tools", "status": "ready"}
