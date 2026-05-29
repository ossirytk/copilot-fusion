"""Tools domain registration for copilot-fusion."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, deque
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
_FILE_LINE_CACHE: dict[Path, tuple[int, int, list[str]]] = {}
_DEFAULT_SIGNAL_RE = re.compile(
    r"\b(error|warn|warning|fail|failed|exception|traceback|fatal|panic|timeout)\b", re.IGNORECASE
)
_STACK_RE = re.compile(r"(^\s+at\s+\S)|(^\s*caused by:)|(\bFile \".*\", line \d+\b)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(/[\w.\-]+(?:/[\w.\-]+)+)")
_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_CLASSLIKE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PY_FUNCTION_RE = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(")
_PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b")
_PY_VARIABLE_RE = re.compile(r"^([A-Za-z_]\w*)\s*=\s*.+")
_JS_FUNCTION_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*\(")
_JS_CLASS_RE = re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$]\w*)\b")
_JS_VARIABLE_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=")
_JS_ARROW_FN_RE = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s*)?\(?.*\)?\s*=>")
_CALL_EXPR_RE = re.compile(r"(?:^|[^A-Za-z0-9_$])((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*\(")
_CALL_EXPR_EXCLUDE = {
    "await",
    "catch",
    "class",
    "delete",
    "for",
    "function",
    "if",
    "new",
    "return",
    "super",
    "switch",
    "this",
    "throw",
    "try",
    "typeof",
    "while",
    "yield",
}


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


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    if not lines or end_line < start_line:
        return ""
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    if start_idx >= end_idx:
        return ""
    return "\n".join(lines[start_idx:end_idx])


def _extractive_summary(text: str, max_sentences: int) -> tuple[str, list[str], dict[str, object]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "", [], {"total_sentences": 0, "selected_sentences": 0, "truncated": False}

    sentences = [segment.strip() for segment in _SENTENCE_SPLIT_RE.split(normalized) if segment.strip()]
    if not sentences:
        return "", [], {"total_sentences": 0, "selected_sentences": 0, "truncated": False}

    token_freq = Counter(re.findall(r"[A-Za-z_]{4,}", normalized.lower()))
    scored: list[tuple[float, int, str]] = []
    for idx, sentence in enumerate(sentences):
        tokens = re.findall(r"[A-Za-z_]{4,}", sentence.lower())
        score = float(sum(token_freq[token] for token in tokens))
        if _DEFAULT_SIGNAL_RE.search(sentence):
            score += 8.0
        if _STACK_RE.search(sentence):
            score += 4.0
        scored.append((score, idx, sentence))

    limit = max(1, min(max_sentences, 12))
    chosen = sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
    ordered = [item[2] for item in sorted(chosen, key=lambda item: item[1])]
    summary = " ".join(ordered)
    stats = {
        "total_sentences": len(sentences),
        "selected_sentences": len(ordered),
        "truncated": len(sentences) > len(ordered),
    }
    return summary, ordered, stats


def _extract_entities(text: str, max_per_type: int = 5) -> list[dict[str, object]]:
    entity_hits: dict[str, Counter[str]] = {
        "url": Counter(),
        "path": Counter(),
        "timestamp": Counter(),
        "classlike": Counter(),
    }
    for line in text.splitlines():
        for url in _URL_RE.findall(line):
            entity_hits["url"][url] += 1
        for found_path in _PATH_RE.findall(line):
            entity_hits["path"][found_path] += 1
        for ts in _TS_RE.findall(line):
            entity_hits["timestamp"][ts] += 1
        for token in _CLASSLIKE_RE.findall(line):
            entity_hits["classlike"][token] += 1

    entities: list[dict[str, object]] = []
    for kind, counts in entity_hits.items():
        entities.extend([{"type": kind, "value": value, "count": count} for value, count in counts.most_common(max_per_type)])
    return entities


def _read_cached_lines(path: Path) -> list[str] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (stat.st_mtime_ns, stat.st_size)
    cached = _FILE_LINE_CACHE.get(path)
    if cached and cached[0] == cache_key[0] and cached[1] == cache_key[1]:
        return cached[2]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    _FILE_LINE_CACHE[path] = (cache_key[0], cache_key[1], lines)
    return lines


def _remote_text_summary(text: str, max_sentences: int, endpoint: str, token: str = "") -> dict[str, object]:
    payload = json.dumps({"text": text, "max_sentences": max_sentences}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            raw_bytes = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        return {"error": f"Remote summarization request failed: {exc}"}
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {"error": f"Remote summarization returned non-UTF8 response: {exc}"}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"error": f"Remote summarization returned invalid JSON: {exc}"}

    if not isinstance(data, dict):
        return {"error": "Remote summarization response must be a JSON object."}

    summary = str(data.get("summary", "")).strip()
    bullets = data.get("bullets", [])
    if not isinstance(bullets, list):
        bullets = []
    stats = data.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}
    if not summary:
        return {"error": "Remote summarization response did not include a summary."}

    return {
        "summary": summary,
        "bullets": [str(item) for item in bullets[: max(1, max_sentences)]],
        "stats": stats,
        "backend": "remote",
    }


def _match_symbol_from_line(line: str, language: str, selected_kinds: set[str]) -> tuple[str, str]:
    if language == "python":
        if "function" in selected_kinds:
            match = _PY_FUNCTION_RE.match(line)
            if match:
                return "function", match.group(1)
        if "class" in selected_kinds:
            match = _PY_CLASS_RE.match(line)
            if match:
                return "class", match.group(1)
        if "variable" in selected_kinds:
            match = _PY_VARIABLE_RE.match(line)
            if match:
                return "variable", match.group(1)
        return "", ""

    if "function" in selected_kinds:
        match = _JS_FUNCTION_RE.match(line) or _JS_ARROW_FN_RE.match(line)
        if match:
            return "function", match.group(1)
    if "class" in selected_kinds:
        match = _JS_CLASS_RE.match(line)
        if match:
            return "class", match.group(1)
    if "variable" in selected_kinds:
        match = _JS_VARIABLE_RE.match(line)
        if match:
            return "variable", match.group(1)
    return "", ""


def _collect_references(
    files: list[tuple[Path, str]],
    symbol: str,
    symbol_kind: str,
    declaration_path: str,
    declaration_line: int,
    max_items: int,
    include_callsites: bool = False,
    file_cache: dict[Path, list[str]] | None = None,
) -> list[dict[str, object]]:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    call_pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(")
    references: list[dict[str, object]] = []
    for candidate, language in files:
        lines = file_cache.get(candidate) if file_cache is not None else None
        if lines is None:
            lines = _read_cached_lines(candidate)
            if lines is None:
                continue
            if file_cache is not None:
                file_cache[candidate] = lines
        for line_no, line in enumerate(lines, start=1):
            if str(candidate) == declaration_path and line_no == declaration_line:
                continue
            if not pattern.search(line):
                continue
            match_type = "reference"
            stripped = line.strip()
            if include_callsites and symbol_kind == "function":
                is_declaration = False
                if language == "python":
                    is_declaration = bool(stripped.startswith(f"def {symbol}("))
                else:
                    is_declaration = bool(
                        re.match(rf"^(?:export\s+)?(?:async\s+)?function\s+{re.escape(symbol)}\s*\(", stripped)
                    )
                if not is_declaration and call_pattern.search(line):
                    match_type = "callsite"
            references.append(
                {
                    "path": str(candidate),
                    "line": line_no,
                    "language": language,
                    "snippet": line.strip(),
                    "match_type": match_type,
                }
            )
            if len(references) >= max_items:
                return references
    return references


def _owner_map_for_file(file_lines: list[str], language: str) -> dict[int, str]:
    owners: dict[int, str] = {}
    if language == "python":
        stack: list[tuple[int, str]] = []
        for line_no, line in enumerate(file_lines, start=1):
            stripped = line.strip()
            indent = len(line) - len(line.lstrip(" "))
            while stack and indent <= stack[-1][0] and stripped:
                stack.pop()
            match = _PY_FUNCTION_RE.match(line)
            if match:
                stack.append((indent, match.group(1)))
            owners[line_no] = stack[-1][1] if stack else "<module>"
        return owners

    # javascript/typescript: lightweight brace-based ownership
    stack_js: list[tuple[int, str]] = []
    brace_depth = 0
    for line_no, line in enumerate(file_lines, start=1):
        stripped = line.strip()
        while stack_js and brace_depth <= stack_js[-1][0]:
            stack_js.pop()
        match = _JS_FUNCTION_RE.match(line) or _JS_ARROW_FN_RE.match(line)
        if match:
            stack_js.append((brace_depth, match.group(1)))
        owners[line_no] = stack_js[-1][1] if stack_js else "<module>"
        open_count = stripped.count("{")
        close_count = stripped.count("}")
        brace_depth = max(0, brace_depth + open_count - close_count)
    return owners


def _declaration_body_range(file_lines: list[str], language: str, declaration_line: int) -> tuple[int, int]:
    if declaration_line < 1 or declaration_line > len(file_lines):
        return declaration_line, declaration_line

    if language == "python":
        declaration_indent = len(file_lines[declaration_line - 1]) - len(file_lines[declaration_line - 1].lstrip(" "))
        end_line = len(file_lines)
        for line_no in range(declaration_line + 1, len(file_lines) + 1):
            line = file_lines[line_no - 1]
            stripped = line.strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= declaration_indent:
                end_line = line_no - 1
                break
        return declaration_line, max(declaration_line, end_line)

    brace_depth = 0
    saw_open = False
    end_line = len(file_lines)
    for line_no in range(declaration_line, len(file_lines) + 1):
        line = file_lines[line_no - 1]
        open_count = line.count("{")
        close_count = line.count("}")
        brace_depth += open_count - close_count
        if open_count > 0:
            saw_open = True
        if saw_open and brace_depth <= 0 and line_no > declaration_line:
            end_line = line_no
            break
    return declaration_line, max(declaration_line, end_line)


def _collect_callgraph(
    files: list[tuple[Path, str]],
    symbol: str,
    symbol_kind: str,
    declaration_path: str,
    declaration_line: int,
    max_items: int,
    file_cache: dict[Path, list[str]] | None = None,
) -> dict[str, object]:
    if symbol_kind != "function":
        return {"callers": [], "sites": [], "callees": [], "callee_sites": [], "truncated": False}

    call_pattern = re.compile(rf"\b{re.escape(symbol)}\s*\(")
    callee_pattern = _CALL_EXPR_RE
    callers: set[str] = set()
    sites: list[dict[str, object]] = []
    callee_counts: Counter[str] = Counter()
    callee_sites: list[dict[str, object]] = []
    truncated = False

    for candidate, language in files:
        lines = file_cache.get(candidate) if file_cache is not None else None
        if lines is None:
            lines = _read_cached_lines(candidate)
            if lines is None:
                continue
            if file_cache is not None:
                file_cache[candidate] = lines
        owners = _owner_map_for_file(lines, language)
        declaration_body_start, declaration_body_end = (
            _declaration_body_range(lines, language, declaration_line)
            if str(candidate) == declaration_path
            else (0, -1)
        )
        for line_no, line in enumerate(lines, start=1):
            if str(candidate) == declaration_path and line_no == declaration_line:
                continue
            if not call_pattern.search(line):
                pass
            else:
                owner = owners.get(line_no, "<module>")
                callers.add(owner)
                if len(sites) < max_items:
                    sites.append(
                        {
                            "path": str(candidate),
                            "line": line_no,
                            "language": language,
                            "caller": owner,
                            "snippet": line.strip(),
                        }
                    )
                else:
                    truncated = True

            if not (str(candidate) == declaration_path and declaration_body_start <= line_no <= declaration_body_end):
                continue
            for match in callee_pattern.finditer(line):
                callee = match.group(1)
                if callee == symbol or callee in _CALL_EXPR_EXCLUDE:
                    continue
                callee_counts[callee] += 1
                if len(callee_sites) < max_items:
                    callee_sites.append(
                        {
                            "path": str(candidate),
                            "line": line_no,
                            "language": language,
                            "callee": callee,
                            "snippet": line.strip(),
                        }
                    )
                else:
                    truncated = True

    return {
        "callers": sorted(callers),
        "sites": sites,
        "site_count": len(sites),
        "callees": [{"symbol": name, "count": count} for name, count in callee_counts.most_common()],
        "callee_sites": callee_sites,
        "truncated": truncated,
    }


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
        max_bytes: int = 200_000,
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
        input_truncated = False
        if path:
            try:
                resolved = resolve_path(path)
                file_size = resolved.stat().st_size
                with resolved.open("rb") as fh:
                    data = fh.read(max_bytes if max_bytes > 0 else -1)
                source_text = data.decode("utf-8", errors="replace")
                input_truncated = max_bytes > 0 and file_size > max_bytes
            except OSError as exc:
                return {"error": f"Failed to read file: {exc}"}

        lines = source_text.splitlines()
        points = max(1, min(max_points, 200))
        candidates: list[dict[str, object]] = []
        pattern_hits = Counter()

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

            candidates.append({"line": line_no, "text": line, "score": score, "reasons": reasons})

        if not candidates:
            fallback = [
                {"line": i + 1, "text": ln.strip(), "score": 0, "reasons": ["fallback"]} for i, ln in enumerate(lines)
            ]
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
        entities = _extract_entities(source_text)

        bullets = [entry["text"] for entry in selected[: min(5, len(selected))]]
        avg_score = mean([int(item["score"]) for item in candidates]) if candidates else 0.0
        summary = (
            f"Selected {len(selected)} high-signal lines from {len(lines)} input lines (avg score {avg_score:.2f})."
        )
        return {
            "summary": summary,
            "bullets": bullets,
            "patterns": top_patterns,
            "entities": entities,
            "stats": {
                "input_lines": len(lines),
                "selected_lines": len(selected),
                "truncated": input_truncated or len(candidates) > len(selected),
            },
            "backend": "deterministic",
            "selected": selected,
        }

    @mcp.tool
    def text_summarize(
        text: str = "",
        path: str = "",
        max_sentences: int = 3,
        backend: str = "auto",
        include_entities: bool = False,
        max_entities: int = 10,
    ) -> dict[str, object]:
        _REQUESTS["text_summarize"] += 1
        if not text and not path:
            return {"error": "Either text or path must be provided."}
        if backend not in {"auto", "extractive", "remote"}:
            return {"error": f"Unsupported backend: {backend}"}

        source_text = text
        if path:
            try:
                source_text = resolve_path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return {"error": f"Failed to read file: {exc}"}

        remote_endpoint = os.getenv("FUSION_TEXT_SUMMARIZER_URL", "").strip()
        remote_token = os.getenv("FUSION_TEXT_SUMMARIZER_TOKEN", "").strip()
        if backend == "remote":
            if not remote_endpoint:
                return {"error": "FUSION_TEXT_SUMMARIZER_URL must be set for backend=remote."}
            return _remote_text_summary(
                source_text, max_sentences=max_sentences, endpoint=remote_endpoint, token=remote_token
            )

        if backend == "auto" and remote_endpoint:
            remote_result = _remote_text_summary(
                source_text, max_sentences=max_sentences, endpoint=remote_endpoint, token=remote_token
            )
            if "error" not in remote_result:
                return remote_result

        summary, bullets, summary_stats = _extractive_summary(source_text, max_sentences=max_sentences)
        chosen_backend = "local-extractive"
        result = {
            "summary": summary,
            "bullets": bullets,
            "backend": chosen_backend,
            "stats": {
                "input_chars": len(source_text),
                "input_lines": len(source_text.splitlines()),
                **summary_stats,
            },
        }
        if include_entities:
            entities = _extract_entities(source_text, max_per_type=max(1, max_entities))
            result["entities"] = entities
            result["stats"]["entity_count"] = len(entities)
        return result

    @mcp.tool
    def apply_text_patch(
        path: str,
        edits: list[dict[str, object]],
        dry_run: bool = False,
        include_preview: bool = False,
        create: bool = False,
        expected_hash: str = "",
        workspace_root: str = "",
    ) -> dict[str, object]:
        _REQUESTS["apply_text_patch"] += 1
        if not edits:
            return {"error": "edits must contain at least one edit item."}

        effective_workspace_root = workspace_root.strip() or os.getenv("FUSION_WORKSPACE_ROOT", "").strip()
        if not effective_workspace_root:
            return {
                "error": "workspace_root is required (or set FUSION_WORKSPACE_ROOT).",
                "details": {"type": "workspace-root-required"},
            }
        resolved = resolve_path(path)
        root = resolve_path(effective_workspace_root)
        try:
            resolved.relative_to(root)
        except ValueError:
            return {
                "error": "Target path is outside configured workspace_root.",
                "details": {
                    "type": "path-outside-root",
                    "path": str(resolved),
                    "workspace_root": str(root),
                },
            }
        exists = resolved.exists()
        if exists and resolved.is_dir():
            return {"error": "Path points to a directory, expected a file."}
        if not exists and not create:
            return {"error": "Target file does not exist. Set create=true to create it."}

        original_text = ""
        if exists:
            try:
                original_text = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return {"error": f"Failed to read file: {exc}"}
        before_hash = _sha256_text(original_text)
        if expected_hash and expected_hash != before_hash:
            return {"error": "expected_hash does not match current file content.", "before_hash": before_hash}

        lines = original_text.splitlines()
        has_trailing_newline = original_text.endswith("\n")
        parsed_edits: list[dict[str, object]] = []
        preview_edits: list[dict[str, object]] = []
        allowed_ops = {"replace", "delete", "insert_before", "insert_after"}

        for idx, edit in enumerate(edits, start=1):
            op = str(edit.get("op", "replace"))
            if op not in allowed_ops:
                return {"error": f"Edit #{idx} has invalid op {op!r}. Allowed ops: {sorted(allowed_ops)}."}
            try:
                anchor_line = int(edit.get("line", edit.get("start_line", 0)))
            except (TypeError, ValueError):
                return {"error": f"Edit #{idx} line/start_line must be an integer."}

            if op in {"replace", "delete"}:
                if "start_line" not in edit or "end_line" not in edit:
                    return {"error": f"Edit #{idx} must include start_line and end_line for op={op}."}
                try:
                    start_line = int(edit["start_line"])
                    end_line = int(edit["end_line"])
                except (TypeError, ValueError):
                    return {"error": f"Edit #{idx} start_line/end_line must be integers."}
            elif op == "insert_before":
                start_line = anchor_line
                end_line = anchor_line - 1
            else:  # insert_after
                start_line = anchor_line + 1
                end_line = anchor_line

            if start_line < 1:
                return {"error": f"Edit #{idx} start_line must be >= 1."}
            if end_line < start_line - 1:
                return {"error": f"Edit #{idx} end_line must be >= start_line - 1."}
            if start_line > len(lines) + 1:
                return {"error": f"Edit #{idx} start_line is out of range for current file length {len(lines)}."}
            if end_line > len(lines):
                return {"error": f"Edit #{idx} end_line is out of range for current file length {len(lines)}."}

            if op == "delete":
                replacement: list[str] = []
            else:
                if "content" not in edit:
                    return {"error": f"Edit #{idx} must include content for op={op}."}
                replacement = str(edit["content"]).splitlines()
            parsed_edits.append(
                {
                    "index": idx,
                    "op": op,
                    "start_line": start_line,
                    "end_line": end_line,
                    "replacement": replacement,
                }
            )
            if dry_run or include_preview:
                before_content = _slice_lines(lines, start_line, end_line)
                after_content = "\n".join(replacement)
                preview_edits.append(
                    {
                        "index": idx,
                        "op": op,
                        "target": {
                            "start_line": start_line,
                            "end_line": end_line,
                        },
                        "before": {
                            "content": before_content,
                            "line_count": 0 if not before_content else before_content.count("\n") + 1,
                        },
                        "after": {
                            "content": after_content,
                            "line_count": 0 if not after_content else after_content.count("\n") + 1,
                        },
                    }
                )

        # Validate conflicts against original coordinates.
        consumed_ranges: list[tuple[int, int, int]] = []
        insertion_anchors: list[tuple[int, int]] = []
        for edit in parsed_edits:
            start_line = int(edit["start_line"])
            end_line = int(edit["end_line"])
            idx = int(edit["index"])
            if end_line >= start_line:
                consumed_ranges.append((start_line, end_line, idx))
            else:
                insertion_anchors.append((start_line, idx))

        for i, (start_a, end_a, idx_a) in enumerate(consumed_ranges):
            for start_b, end_b, idx_b in consumed_ranges[i + 1 :]:
                if start_a <= end_b and start_b <= end_a:
                    return {
                        "error": "Edits overlap; each edit must target a distinct line range.",
                        "details": {
                            "type": "overlap",
                            "edit_a": {"index": idx_a, "start_line": start_a, "end_line": end_a},
                            "edit_b": {"index": idx_b, "start_line": start_b, "end_line": end_b},
                        },
                    }

        for i, (anchor_a, idx_a) in enumerate(insertion_anchors):
            for anchor_b, idx_b in insertion_anchors[i + 1 :]:
                if anchor_a == anchor_b:
                    return {
                        "error": "Insertion edits conflict at the same anchor.",
                        "details": {
                            "type": "insertion-anchor-conflict",
                            "edit_a": {"index": idx_a, "anchor_line": anchor_a},
                            "edit_b": {"index": idx_b, "anchor_line": anchor_b},
                        },
                    }

        for anchor, idx_anchor in insertion_anchors:
            for start_line, end_line, idx_consume in consumed_ranges:
                if start_line <= anchor <= end_line + 1:
                    return {
                        "error": "Insertion conflicts with a replace/delete range.",
                        "details": {
                            "type": "insert-range-conflict",
                            "insert_edit": {"index": idx_anchor, "anchor_line": anchor},
                            "range_edit": {"index": idx_consume, "start_line": start_line, "end_line": end_line},
                        },
                    }

        updated_lines = list(lines)
        for edit in sorted(parsed_edits, key=lambda item: int(item["start_line"]), reverse=True):
            start_idx = int(edit["start_line"]) - 1
            end_line = int(edit["end_line"])
            replacement = list(edit["replacement"])
            if end_line < int(edit["start_line"]):
                updated_lines[start_idx:start_idx] = replacement
                continue
            updated_lines[start_idx:end_line] = replacement

        if updated_lines:
            result_text = "\n".join(updated_lines) + ("\n" if has_trailing_newline else "")
        else:
            result_text = ""
        after_hash = _sha256_text(result_text)
        changed = after_hash != before_hash

        if not dry_run and changed:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(result_text, encoding="utf-8")

        result = {
            "path": str(resolved),
            "applied": len(parsed_edits),
            "changed": changed,
            "dry_run": dry_run,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "line_count_before": len(lines),
            "line_count_after": len(updated_lines),
            "workspace_root": str(root),
            "normalized_edits": [
                {
                    "index": int(edit["index"]),
                    "op": str(edit["op"]),
                    "start_line": int(edit["start_line"]),
                    "end_line": int(edit["end_line"]),
                    "replacement_lines": len(list(edit["replacement"])),
                }
                for edit in parsed_edits
            ],
        }
        if dry_run or include_preview:
            result["preview"] = {
                "edits": preview_edits,
                "result": {
                    "content": result_text,
                    "line_count": len(updated_lines),
                },
            }
        return result

    @mcp.tool
    def apply_text_patch_batch(
        patches: list[dict[str, object]],
        dry_run: bool = False,
        workspace_root: str = "",
    ) -> dict[str, object]:
        _REQUESTS["apply_text_patch_batch"] += 1
        if not patches:
            return {"error": "patches must contain at least one patch item."}

        results: list[dict[str, object]] = []
        changed = 0
        applied = 0
        failed = 0
        for index, patch in enumerate(patches, start=1):
            if not isinstance(patch, dict):
                failed += 1
                results.append({"index": index, "error": "Each patch item must be a JSON object."})
                continue
            path = str(patch.get("path", "")).strip()
            edits = patch.get("edits", [])
            patch_dry_run = bool(patch.get("dry_run", dry_run))
            patch_workspace_root = str(patch.get("workspace_root", workspace_root)).strip()
            result = apply_text_patch(
                path=path,
                edits=edits if isinstance(edits, list) else [],
                dry_run=patch_dry_run,
                include_preview=bool(patch.get("include_preview", patch_dry_run)),
                create=bool(patch.get("create", False)),
                expected_hash=str(patch.get("expected_hash", "")),
                workspace_root=patch_workspace_root,
            )
            if "error" in result:
                failed += 1
            else:
                applied += 1
                if result.get("changed"):
                    changed += 1
            result["index"] = index
            results.append(result)

        return {
            "results": results,
            "applied": applied,
            "changed": changed,
            "failed": failed,
            "dry_run": dry_run,
        }

    @mcp.tool
    def symbol_search(
        paths: list[str],
        query: str = "",
        kinds: list[str] | None = None,
        max_results: int = 500,
        include_references: bool = False,
        include_callsites: bool = False,
        max_references_per_symbol: int = 10,
        include_callgraph: bool = False,
        max_callgraph_edges: int = 50,
    ) -> dict[str, object]:
        _REQUESTS["symbol_search"] += 1
        if not paths:
            return {"error": "paths must contain at least one file or directory."}

        allowed_kinds = {"function", "class", "variable"}
        selected_kinds = set(kinds or ["function", "class", "variable"])
        invalid_kinds = selected_kinds - allowed_kinds
        if invalid_kinds:
            return {"error": f"Invalid kinds: {sorted(invalid_kinds)}. Allowed kinds: {sorted(allowed_kinds)}"}

        candidates: list[tuple[Path, str]] = []
        for source in paths:
            resolved = resolve_path(source)
            if resolved.is_dir():
                for suffix, language in (
                    ("*.py", "python"),
                    ("*.js", "javascript"),
                    ("*.jsx", "javascript"),
                    ("*.mjs", "javascript"),
                    ("*.cjs", "javascript"),
                    ("*.ts", "typescript"),
                    ("*.tsx", "typescript"),
                ):
                    candidates.extend([(p, language) for p in resolved.rglob(suffix) if p.is_file()])
            elif resolved.is_file():
                suffix = resolved.suffix.lower()
                if suffix == ".py":
                    candidates.append((resolved, "python"))
                elif suffix in {".js", ".jsx", ".mjs", ".cjs"}:
                    candidates.append((resolved, "javascript"))
                elif suffix in {".ts", ".tsx"}:
                    candidates.append((resolved, "typescript"))

        q = query.lower().strip()
        results: list[dict[str, object]] = []
        file_cache: dict[Path, list[str]] = {}

        for candidate, language in candidates:
            file_lines = file_cache.get(candidate)
            if file_lines is None:
                file_lines = _read_cached_lines(candidate)
                if file_lines is None:
                    continue
                file_cache[candidate] = file_lines
            for line_no, line in enumerate(file_lines, start=1):
                symbol_kind, symbol_name = _match_symbol_from_line(
                    line, language=language, selected_kinds=selected_kinds
                )
                if not symbol_kind:
                    continue
                if q and q not in symbol_name.lower():
                    continue
                column = line.find(symbol_name) + 1
                indent = len(line) - len(line.lstrip(" "))
                item: dict[str, object] = {
                    "path": str(candidate),
                    "line": line_no,
                    "column": column if column > 0 else 1,
                    "symbol": symbol_name,
                    "kind": symbol_kind,
                    "language": language,
                    "signature": line.strip(),
                    "indent": indent,
                }
                if include_references:
                    refs = _collect_references(
                        candidates,
                        symbol=symbol_name,
                        symbol_kind=symbol_kind,
                        declaration_path=str(candidate),
                        declaration_line=line_no,
                        max_items=max(1, max_references_per_symbol),
                        include_callsites=include_callsites,
                        file_cache=file_cache,
                    )
                    item["references"] = {
                        "count": len(refs),
                        "callsite_count": sum(1 for ref in refs if ref.get("match_type") == "callsite"),
                        "items": refs,
                        "truncated": len(refs) >= max(1, max_references_per_symbol),
                    }
                if include_callgraph:
                    item["callgraph"] = _collect_callgraph(
                        candidates,
                        symbol=symbol_name,
                        symbol_kind=symbol_kind,
                        declaration_path=str(candidate),
                        declaration_line=line_no,
                        max_items=max(1, max_callgraph_edges),
                        file_cache=file_cache,
                    )
                results.append(item)
                if len(results) >= max(1, max_results):
                    return {"results": results, "truncated": True}
        return {"results": results, "truncated": False}

    @mcp.tool
    def read_file(
        path: str,
        start_line: int = 1,
        end_line: int = -1,
        max_bytes: int = 200_000,
        compact: bool = False,
        compact_mode: str = "auto",
        compact_max_points: int = 20,
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
        result = {
            "path": str(resolved),
            "content": "\n".join(selected),
            "start_line": s,
            "end_line": e,
            "truncated": truncated,
            "bytes_read": len(data),
        }
        if compact:
            compact_result = text_compact(text=result["content"], mode=compact_mode, max_points=compact_max_points)
            result["compact"] = compact_result
        return result

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
