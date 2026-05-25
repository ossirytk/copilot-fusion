"""Structured diff tools for copilot-fusion."""

from __future__ import annotations

import difflib
import re

from fastmcp import FastMCP
from copilot_fusion_shared import resolve_path, run_command


def _parse_unified_diff(diff_text: str) -> list[dict[str, object]]:
    """Parse unified diff text into a list of per-file structured dicts."""
    files: list[dict[str, object]] = []
    current_file: dict[str, object] | None = None
    current_hunk: dict[str, object] | None = None

    file_header_re = re.compile(r"^\+\+\+ b/(.+)$")
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    for raw_line in diff_text.splitlines():
        file_match = file_header_re.match(raw_line)
        if file_match:
            if current_hunk and current_file is not None:
                current_file["hunks"].append(current_hunk)  # type: ignore[union-attr]
                current_hunk = None
            current_file = {
                "path": file_match.group(1),
                "additions": 0,
                "deletions": 0,
                "hunks": [],
            }
            files.append(current_file)
            continue

        hunk_match = hunk_header_re.match(raw_line)
        if hunk_match and current_file is not None:
            if current_hunk is not None:
                current_file["hunks"].append(current_hunk)  # type: ignore[union-attr]
            current_hunk = {
                "old_start": int(hunk_match.group(1)),
                "old_lines": int(hunk_match.group(2) or 1),
                "new_start": int(hunk_match.group(3)),
                "new_lines": int(hunk_match.group(4) or 1),
                "lines": [],
            }
            continue

        if current_hunk is None or current_file is None:
            continue

        if raw_line.startswith("+"):
            current_hunk["lines"].append({"type": "addition", "content": raw_line[1:]})  # type: ignore[union-attr]
            current_file["additions"] = int(current_file["additions"]) + 1  # type: ignore[arg-type]
        elif raw_line.startswith("-"):
            current_hunk["lines"].append({"type": "deletion", "content": raw_line[1:]})  # type: ignore[union-attr]
            current_file["deletions"] = int(current_file["deletions"]) + 1  # type: ignore[arg-type]
        elif raw_line.startswith(" "):
            current_hunk["lines"].append({"type": "context", "content": raw_line[1:]})  # type: ignore[union-attr]

    if current_hunk is not None and current_file is not None:
        current_file["hunks"].append(current_hunk)  # type: ignore[union-attr]

    return files


def _summarize_files(files: list[dict[str, object]]) -> dict[str, object]:
    total_add = sum(int(f["additions"]) for f in files)  # type: ignore[arg-type]
    total_del = sum(int(f["deletions"]) for f in files)  # type: ignore[arg-type]
    total_hunks = sum(len(f["hunks"]) for f in files)  # type: ignore[arg-type]
    return {
        "files": files,
        "total_files": len(files),
        "total_additions": total_add,
        "total_deletions": total_del,
        "total_hunks": total_hunks,
    }


def register(mcp: FastMCP) -> None:
    """Register contextwell-diff tools into the provided MCP server."""

    @mcp.tool
    def diff_staged(path: str = ".") -> dict[str, object]:
        """Structured JSON diff of currently staged changes in a git repository."""
        cwd = resolve_path(path)
        result = run_command(["git", "diff", "--staged"], cwd)
        if not result.ok:
            return {"error": result.stderr.strip() or "git diff --staged failed"}
        if not result.stdout.strip():
            return {"files": [], "total_files": 0, "total_additions": 0, "total_deletions": 0, "total_hunks": 0}
        files = _parse_unified_diff(result.stdout)
        return _summarize_files(files)

    @mcp.tool
    def diff_refs(
        ref_a: str,
        ref_b: str,
        path: str = ".",
        file_filter: str = "",
    ) -> dict[str, object]:
        """Structured JSON diff between two git refs (commits, branches, or tags)."""
        cwd = resolve_path(path)
        args = ["git", "diff", ref_a, ref_b]
        if file_filter:
            args.extend(["--", file_filter])
        result = run_command(args, cwd)
        if not result.ok:
            return {"error": result.stderr.strip() or f"git diff {ref_a}..{ref_b} failed"}
        if not result.stdout.strip():
            return {"files": [], "total_files": 0, "total_additions": 0, "total_deletions": 0, "total_hunks": 0}
        files = _parse_unified_diff(result.stdout)
        return _summarize_files(files)

    @mcp.tool
    def diff_files(path_a: str, path_b: str) -> dict[str, object]:
        """Structured JSON diff between two arbitrary files on disk."""
        resolved_a = resolve_path(path_a)
        resolved_b = resolve_path(path_b)
        try:
            lines_a = resolved_a.read_text(encoding="utf-8").splitlines(keepends=True)
            lines_b = resolved_b.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, UnicodeDecodeError) as exc:
            return {"error": str(exc)}
        unified = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=f"a/{resolved_a.name}",
                tofile=f"b/{resolved_b.name}",
            )
        )
        if not unified:
            return {"files": [], "total_files": 0, "total_additions": 0, "total_deletions": 0, "total_hunks": 0}
        diff_text = "".join(unified)
        # unified_diff uses "--- a/..." and "+++ b/..." but _parse_unified_diff looks for "+++ b/"
        # Ensure the header is in the expected shape.
        files = _parse_unified_diff(diff_text)
        if not files:
            # Fallback: construct a minimal file entry from raw counts.
            adds = sum(1 for line in unified if line.startswith("+") and not line.startswith("+++"))
            dels = sum(1 for line in unified if line.startswith("-") and not line.startswith("---"))
            files = [{"path": resolved_b.name, "additions": adds, "deletions": dels, "hunks": []}]
        return _summarize_files(files)

    @mcp.tool
    def summarize_diff(diff_text: str) -> dict[str, object]:
        """Parse a raw unified diff string and return aggregate counts (files, additions, deletions, hunks)."""
        if not diff_text.strip():
            return {"total_files": 0, "total_additions": 0, "total_deletions": 0, "total_hunks": 0, "files": []}
        files = _parse_unified_diff(diff_text)
        summary = _summarize_files(files)
        # Return summary without full hunk lines to keep the response compact.
        compact_files = [
            {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"], "hunks": len(f["hunks"])}  # type: ignore[arg-type]
            for f in files
        ]
        return {
            "total_files": summary["total_files"],
            "total_additions": summary["total_additions"],
            "total_deletions": summary["total_deletions"],
            "total_hunks": summary["total_hunks"],
            "files": compact_files,
        }

    @mcp.tool(name="fusion_diff_health")
    def fusion_diff_health() -> dict[str, str]:
        return {"domain": "diff", "status": "ready"}
