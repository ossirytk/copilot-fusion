"""Tools domain registration for copilot-fusion."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from pathlib import Path
from statistics import mean
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
_DEFAULT_SIGNAL_RE = re.compile(r"\b(error|warn|warning|fail|failed|exception|traceback|fatal|panic|timeout)\b", re.IGNORECASE)
_STACK_RE = re.compile(r"(^\s+at\s+\S)|(^\s*caused by:)|(\bFile \".*\", line \d+\b)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(/[\w.\-]+(?:/[\w.\-]+)+)")
_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_CLASSLIKE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")


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


def _compile_patterns(patterns: list[str] | None) -> tuple[list[re.Pattern[str]], str | None]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns or []:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            return [], f"Invalid regex pattern: {pattern!r} ({exc})"
    return compiled, None


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
    def text_compact(
        text: str = "",
        path: str = "",
        mode: str = "auto",
        max_points: int = 20,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> dict[str, object]:
        _REQUESTS["text_compact"] += 1
        if not text and not path:
            return {"error": "Either text or path must be provided."}
        if mode not in {"auto", "errors-first"}:
            return {"error": f"Unsupported mode: {mode}"}

        include_re, include_err = _compile_patterns(include_patterns)
        if include_err:
            return {"error": include_err}
        exclude_re, exclude_err = _compile_patterns(exclude_patterns)
        if exclude_err:
            return {"error": exclude_err}

        source_text = text
        if path:
            try:
                source_text = resolve_path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return {"error": f"Failed to read file: {exc}"}

        lines = source_text.splitlines()
        points = max(1, min(max_points, 200))
        candidates: list[dict[str, object]] = []
        pattern_hits = Counter()
        entity_hits: dict[str, Counter[str]] = {"url": Counter(), "path": Counter(), "timestamp": Counter()}

        for line_no, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if any(rx.search(line) for rx in exclude_re):
                continue

            score = 0
            reasons: list[str] = []
            if _DEFAULT_SIGNAL_RE.search(line):
                score += 4
                reasons.append("signal")
            if _STACK_RE.search(line):
                score += 2
                reasons.append("stack")
            if include_re and any(rx.search(line) for rx in include_re):
                score += 3
                reasons.append("include")
            if mode == "errors-first" and score == 0:
                continue

            for match in _CLASSLIKE_RE.findall(line):
                pattern_hits[match] += 1
            for keyword in ("error", "warning", "exception", "timeout", "failed", "panic"):
                if re.search(rf"\b{keyword}\b", line, re.IGNORECASE):
                    pattern_hits[keyword] += 1

            for url in _URL_RE.findall(line):
                entity_hits["url"][url] += 1
            for found_path in _PATH_RE.findall(line):
                entity_hits["path"][found_path] += 1
            for ts in _TS_RE.findall(line):
                entity_hits["timestamp"][ts] += 1

            candidates.append({"line": line_no, "text": line, "score": score, "reasons": reasons})

        if not candidates:
            fallback = [{"line": i + 1, "text": ln.strip(), "score": 0, "reasons": ["fallback"]} for i, ln in enumerate(lines)]
            candidates = [c for c in fallback if c["text"]]

        ranked = sorted(candidates, key=lambda item: (int(item["score"]), -int(item["line"])), reverse=True)
        selected: list[dict[str, object]] = []
        seen = set()
        for item in ranked:
            if item["text"] in seen:
                continue
            seen.add(str(item["text"]))
            selected.append(
                {
                    "line": item["line"],
                    "text": item["text"],
                    "reason": ",".join(item["reasons"]) if item["reasons"] else "context",
                }
            )
            if len(selected) >= points:
                break

        top_patterns = [{"pattern": key, "count": count} for key, count in pattern_hits.most_common(10)]
        entities: list[dict[str, object]] = []
        for kind, counts in entity_hits.items():
            entities.extend([{"type": kind, "value": value, "count": count} for value, count in counts.most_common(5)])

        bullets = [entry["text"] for entry in selected[: min(5, len(selected))]]
        avg_score = mean([int(item["score"]) for item in candidates]) if candidates else 0.0
        summary = f"Selected {len(selected)} high-signal lines from {len(lines)} input lines (avg score {avg_score:.2f})."
        return {
            "summary": summary,
            "bullets": bullets,
            "patterns": top_patterns,
            "entities": entities,
            "stats": {
                "input_lines": len(lines),
                "selected_lines": len(selected),
                "truncated": len(candidates) > len(selected),
            },
            "backend": "deterministic",
            "selected": selected,
        }

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
