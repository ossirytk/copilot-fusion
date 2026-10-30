"""Tools domain registration for copilot-fusion."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from copilot_fusion_shared import resolve_path
from fastmcp import FastMCP

from contextwell_tools import symbols
from contextwell_tools.execution import register_execution

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


_REQUESTS = Counter()
_DEFAULT_SIGNAL_RE = re.compile(
    r"\b(error|warn|warning|fail|failed|exception|traceback|fatal|panic|timeout)\b", re.IGNORECASE
)
_STACK_RE = re.compile(r"(^\s+at\s+\S)|(^\s*caused by:)|(\bFile \".*\", line \d+\b)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(/[\w.\-]+(?:/[\w.\-]+)+)")
_TS_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-2]\d:[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_CLASSLIKE_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning))\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


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


def _extract_entities(text: str, max_per_type: int = 5, max_total: int | None = None) -> list[dict[str, object]]:
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
        entities.extend(
            [{"type": kind, "value": value, "count": count} for value, count in counts.most_common(max_per_type)]
        )
    if max_total is not None:
        entities.sort(key=lambda e: int(e["count"]), reverse=True)
        entities = entities[:max_total]
    return entities


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


def _score_compact_line(
    line: str,
    include_re: list[re.Pattern[str]],
    exclude_re: list[re.Pattern[str]],
    mode: str,
    pattern_hits: Counter[str],
) -> tuple[int, list[str]] | None:
    """Score a single line for text_compact and update pattern hits. Return None if line is skipped."""
    if not line or any(rx.search(line) for rx in exclude_re):
        return None

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
        return None

    for match in _CLASSLIKE_RE.findall(line):
        pattern_hits[match] += 1
    for keyword in ("error", "warning", "exception", "timeout", "failed", "panic"):
        if re.search(rf"\b{keyword}\b", line, re.IGNORECASE):
            pattern_hits[keyword] += 1

    return score, reasons


def _select_compact_candidates(
    lines: list[str],
    include_re: list[re.Pattern[str]],
    exclude_re: list[re.Pattern[str]],
    mode: str,
) -> tuple[list[dict[str, object]], Counter[str]]:
    """Scan and score candidate lines for text_compact."""
    candidates: list[dict[str, object]] = []
    pattern_hits: Counter[str] = Counter()

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        scored = _score_compact_line(line, include_re, exclude_re, mode, pattern_hits)
        if scored is None:
            continue
        score, reasons = scored
        candidates.append({"line": line_no, "text": line, "score": score, "reasons": reasons})

    if not candidates:
        fallback = [
            {"line": i + 1, "text": ln.strip(), "score": 0, "reasons": ["fallback"]} for i, ln in enumerate(lines)
        ]
        candidates = [c for c in fallback if c["text"]]

    return candidates, pattern_hits


def _rank_and_select_lines(
    candidates: list[dict[str, object]],
    points: int,
) -> list[dict[str, object]]:
    """Rank candidates by score and select top unique entries."""
    ranked = sorted(candidates, key=lambda item: (int(item["score"]), -int(item["line"])), reverse=True)
    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in ranked:
        text_str = str(item["text"])
        if text_str in seen:
            continue
        seen.add(text_str)
        selected.append(
            {
                "line": item["line"],
                "text": item["text"],
                "reason": ",".join(item["reasons"]) if item["reasons"] else "context",
            }
        )
        if len(selected) >= points:
            break
    return selected


def _parse_single_patch_edit(
    edit: dict[str, object],
    idx: int,
    file_line_count: int,
    lines: list[str],
    dry_run: bool,
    include_preview: bool,
) -> tuple[dict[str, object] | None, dict[str, object] | None, dict[str, object] | None]:
    """Parse and validate one patch edit. Returns (parsed_edit, preview_edit, error_dict)."""
    allowed_ops = {"replace", "delete", "insert_before", "insert_after"}
    op = str(edit.get("op", "replace"))
    if op not in allowed_ops:
        return None, None, {"error": f"Edit #{idx} has invalid op {op!r}. Allowed ops: {sorted(allowed_ops)}."}

    try:
        anchor_line = int(edit.get("line", edit.get("start_line", 0)))
    except (TypeError, ValueError):
        return None, None, {"error": f"Edit #{idx} line/start_line must be an integer."}

    if op in {"replace", "delete"}:
        if "start_line" not in edit or "end_line" not in edit:
            return None, None, {"error": f"Edit #{idx} must include start_line and end_line for op={op}."}
        try:
            start_line = int(edit["start_line"])
            end_line = int(edit["end_line"])
        except (TypeError, ValueError):
            return None, None, {"error": f"Edit #{idx} start_line/end_line must be integers."}
    elif op == "insert_before":
        start_line = anchor_line
        end_line = anchor_line - 1
    else:  # insert_after
        start_line = anchor_line + 1
        end_line = anchor_line

    if start_line < 1:
        return None, None, {"error": f"Edit #{idx} start_line must be >= 1."}
    if end_line < start_line - 1:
        return None, None, {"error": f"Edit #{idx} end_line must be >= start_line - 1."}
    if start_line > file_line_count + 1:
        return (
            None,
            None,
            {"error": f"Edit #{idx} start_line is out of range for current file length {file_line_count}."},
        )
    if end_line > file_line_count:
        return None, None, {"error": f"Edit #{idx} end_line is out of range for current file length {file_line_count}."}

    if op == "delete":
        replacement: list[str] = []
    else:
        if "content" not in edit:
            return None, None, {"error": f"Edit #{idx} must include content for op={op}."}
        replacement = str(edit["content"]).splitlines()

    parsed = {
        "index": idx,
        "op": op,
        "start_line": start_line,
        "end_line": end_line,
        "replacement": replacement,
    }
    preview: dict[str, object] | None = None
    if dry_run or include_preview:
        before_content = _slice_lines(lines, start_line, end_line)
        after_content = "\n".join(replacement)
        preview = {
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

    return parsed, preview, None


def _check_patch_conflicts(parsed_edits: list[dict[str, object]]) -> dict[str, object] | None:
    """Check for range overlaps and anchor collisions among parsed patch edits."""
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
    return None


def _apply_parsed_edits(lines: list[str], parsed_edits: list[dict[str, object]]) -> list[str]:
    """Apply sorted parsed edits to lines from bottom to top."""
    updated_lines = list(lines)
    for edit in sorted(parsed_edits, key=lambda item: int(item["start_line"]), reverse=True):
        start_idx = int(edit["start_line"]) - 1
        end_line = int(edit["end_line"])
        replacement = list(edit["replacement"])
        if end_line < int(edit["start_line"]):
            updated_lines[start_idx:start_idx] = replacement
            continue
        updated_lines[start_idx:end_line] = replacement
    return updated_lines


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


def text_compact(
    text: str = "",
    path: str = "",
    mode: str = "auto",
    max_points: int = 20,
    max_bytes: int = 200_000,
    max_entities: int = 10,
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
    candidates, pattern_hits = _select_compact_candidates(lines, include_re, exclude_re, mode)
    selected = _rank_and_select_lines(candidates, points)

    top_patterns = [{"pattern": key, "count": count} for key, count in pattern_hits.most_common(10)]
    entities = _extract_entities(source_text, max_per_type=max(1, max_entities), max_total=max_entities)

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
            "truncated": input_truncated or len(candidates) > len(selected),
        },
        "backend": "deterministic",
        "selected": selected,
    }


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
        entities = _extract_entities(source_text, max_per_type=max(1, max_entities), max_total=max_entities)
        result["entities"] = entities
        result["stats"]["entity_count"] = len(entities)
    return result


def _resolve_workspace_file_target(
    path: str,
    workspace_root: str,
    create: bool,
) -> tuple[Path | None, Path | None, dict[str, object] | None]:
    """Resolve and validate target file path within workspace root. Returns (resolved_path, root, error)."""
    effective_workspace_root = workspace_root.strip() or os.getenv("FUSION_WORKSPACE_ROOT", "").strip()
    if not effective_workspace_root:
        return (
            None,
            None,
            {
                "error": "workspace_root is required (or set FUSION_WORKSPACE_ROOT).",
                "details": {"type": "workspace-root-required"},
            },
        )
    root = resolve_path(effective_workspace_root)
    p = Path(path).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
    else:
        resolved = (root / p).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return (
            None,
            None,
            {
                "error": "Target path is outside configured workspace_root.",
                "details": {
                    "type": "path-outside-root",
                    "path": str(resolved),
                    "workspace_root": str(root),
                },
            },
        )
    exists = resolved.exists()
    if exists and resolved.is_dir():
        return None, None, {"error": "Path points to a directory, expected a file."}
    if not exists and not create:
        return None, None, {"error": "Target file does not exist. Set create=true to create it."}
    return resolved, root, None


def _load_target_text(resolved: Path, expected_hash: str) -> tuple[str, str, dict[str, object] | None]:
    """Read original text and verify expected hash. Returns (original_text, before_hash, error)."""
    original_text = ""
    if resolved.exists():
        try:
            original_text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return "", "", {"error": f"Failed to read file: {exc}"}
    before_hash = _sha256_text(original_text)
    if expected_hash and expected_hash != before_hash:
        return "", "", {"error": "expected_hash does not match current file content.", "before_hash": before_hash}
    return original_text, before_hash, None


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

    resolved, root, err = _resolve_workspace_file_target(path, workspace_root, create)
    if err or resolved is None or root is None:
        return err or {"error": "Failed to resolve path."}

    exists = resolved.exists()
    original_text, before_hash, hash_err = _load_target_text(resolved, expected_hash)
    if hash_err:
        return hash_err

    lines = original_text.splitlines()
    has_trailing_newline = original_text.endswith("\n")
    parsed_edits: list[dict[str, object]] = []
    preview_edits: list[dict[str, object]] = []

    for idx, edit in enumerate(edits, start=1):
        parsed, preview, edit_err = _parse_single_patch_edit(
            edit, idx, len(lines), lines, dry_run=dry_run, include_preview=include_preview
        )
        if edit_err:
            return edit_err
        if parsed is not None:
            parsed_edits.append(parsed)
        if preview is not None:
            preview_edits.append(preview)

    conflict_err = _check_patch_conflicts(parsed_edits)
    if conflict_err:
        return conflict_err

    updated_lines = _apply_parsed_edits(lines, parsed_edits)

    if updated_lines:
        result_text = "\n".join(updated_lines) + ("\n" if has_trailing_newline else "")
    else:
        result_text = ""
    after_hash = _sha256_text(result_text)
    changed = after_hash != before_hash or not exists

    if not dry_run and changed:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(result_text, encoding="utf-8")
        symbols.invalidate(resolved)

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
    """Find definitions (Tree-sitter parsed) in Python, JavaScript/TypeScript (incl. JSX/TSX) and Go files.

    Supported ``kinds`` values are ``"function"`` (functions and methods), ``"class"`` (classes, plus
    TS interfaces/enums/type aliases and Go types) and ``"variable"`` (module-level only).  Each result has
    ``path``, ``line``, ``column``, ``end_line``, ``symbol``, ``kind`` and ``parent`` (enclosing class/receiver),
    so it can feed ``read_file`` or ``apply_text_patch`` directly.  References and call graphs match by name
    across the given ``paths`` (no import/type resolution); comments and strings are ignored.  When other
    definitions share the name, ``same_name_definitions`` reports how many, as a hint that results may be mixed.
    """
    _REQUESTS["symbol_search"] += 1
    if not paths:
        return {"error": "paths must contain at least one file or directory."}

    allowed_kinds = {"function", "class", "variable"}
    selected_kinds = set(kinds or ["function", "class", "variable"])
    invalid_kinds = selected_kinds - allowed_kinds
    if invalid_kinds:
        return {"error": f"Invalid kinds: {sorted(invalid_kinds)}. Allowed kinds: {sorted(allowed_kinds)}"}

    indexes = symbols.collect_indexes(paths)
    q = query.lower().strip()
    needs_context = include_references or include_callgraph
    name_counts = symbols.count_same_name(indexes) if needs_context else None
    results: list[dict[str, object]] = []

    for index in indexes:
        for definition in index.definitions:
            if definition.kind not in selected_kinds or (q and q not in definition.name.lower()):
                continue
            signature, indent = symbols.signature_of(index, definition)
            item: dict[str, object] = {
                "path": str(index.path),
                "line": definition.line,
                "column": definition.column,
                "end_line": definition.end_line,
                "symbol": definition.name,
                "kind": definition.kind,
                "parent": definition.parent,
                "language": index.language,
                "signature": signature,
                "indent": indent,
            }
            if name_counts is not None:
                others = name_counts[(definition.name, definition.kind)] - 1
                if others > 0:
                    item["same_name_definitions"] = others
            if include_references:
                limit = max(1, max_references_per_symbol)
                refs = symbols.find_references(indexes, definition, index, include_callsites, limit)
                item["references"] = {
                    "count": len(refs),
                    "callsite_count": sum(1 for ref in refs if ref.get("match_type") == "callsite"),
                    "items": refs,
                    "truncated": len(refs) >= limit,
                }
            if include_callgraph:
                item["callgraph"] = symbols.build_callgraph(indexes, definition, index, max(1, max_callgraph_edges))
            results.append(item)
            if len(results) >= max(1, max_results):
                return {"results": results, "truncated": True}
    return {"results": results, "truncated": False}


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


def server_stats() -> dict[str, object]:
    _REQUESTS["server_stats"] += 1
    return {"requests": dict(_REQUESTS)}


def register(mcp: FastMCP, core_only: bool = False) -> None:
    """Register contextwell-tools tools; ``core_only`` registers just ``symbol_search``."""
    mcp.tool(symbol_search)
    if core_only:
        return
    mcp.tool(fs_glob)
    mcp.tool(text_search)
    mcp.tool(text_compact)
    mcp.tool(text_summarize)
    mcp.tool(apply_text_patch)
    mcp.tool(read_file)
    mcp.tool(server_stats)
    try:
        register_execution(mcp)
    except ValueError:
        pass
