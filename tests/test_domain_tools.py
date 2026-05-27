import asyncio
import json
import tempfile
from pathlib import Path

from copilot_fusion.server import create_server


def _call(tool: str, args: dict | None = None) -> object:
    async def _run() -> object:
        server = create_server()
        result = await server.call_tool(tool, args or {})
        payload = result.structured_content
        if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
            return payload["result"]
        return payload

    return asyncio.run(_run())


def test_core_memory_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = _call(
            "remember",
            {
                "content": "fusion-memory-test-entry",
                "scope": "project",
                "source": f"cwd:{tmp}",
                "scope_path": tmp,
            },
        )
        assert isinstance(memory, dict)
        assert "id" in memory

        recalled = _call("recall", {"query": "fusion-memory-test-entry", "scope": "project", "scope_path": tmp})
        assert isinstance(recalled, list)
        assert any(
            "fusion-memory-test-entry" in str(item.get("content", "")) for item in recalled if isinstance(item, dict)
        )


def test_tools_fs_glob_and_json_select() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_text("alpha\n", encoding="utf-8")
        (root / "b.json").write_text(json.dumps([{"name": "alpha"}, {"name": "beta"}]), encoding="utf-8")

        globbed = _call("fs_glob", {"base_path": tmp, "patterns": ["*.txt"]})
        assert isinstance(globbed, dict)
        results = globbed.get("results", [])
        assert any(str(path).endswith("a.txt") for path in results)

        selected = _call(
            "json_select",
            {
                "path": str(root / "b.json"),
                "fields": ["name"],
                "filters": [{"field": "name", "op": "contains", "value": "alpha"}],
            },
        )
        assert isinstance(selected, dict)
        rows = selected.get("results", [])
        assert isinstance(rows, list)
        assert rows and rows[0]["name"] == "alpha"

        read_back = _call("read_file", {"path": str(root / "a.txt")})
        assert isinstance(read_back, dict)
        assert "alpha" in str(read_back.get("content", ""))

        file_digest = _call("file_hash", {"path": str(root / "a.txt"), "algorithm": "sha256"})
        assert isinstance(file_digest, dict)
        assert len(str(file_digest.get("hash", ""))) == 64


def test_git_status_on_initialized_repo() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")

        init = _call("git_status", {"path": tmp})
        if isinstance(init, dict) and "error" in init:
            # Initialize the repo when status fails in a plain directory.
            import subprocess

            subprocess.run(["git", "init"], cwd=tmp, check=False, capture_output=True, text=True)
            init = _call("git_status", {"path": tmp})

        assert isinstance(init, dict)
        assert "error" not in init
        assert "status" in init


def test_diff_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
        (root / "b.txt").write_text("line1\nline2 changed\nline3\nline4\n", encoding="utf-8")

        result = _call("diff_files", {"path_a": str(root / "a.txt"), "path_b": str(root / "b.txt")})
        assert isinstance(result, dict)
        assert result.get("total_files", 0) >= 1
        assert result.get("total_additions", 0) >= 1
        assert result.get("total_deletions", 0) >= 1


def test_diff_staged_empty(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=False, capture_output=True)
    result = _call("diff_staged", {"path": str(tmp_path)})
    assert isinstance(result, dict)
    # No staged changes — expect empty files list.
    assert result.get("total_files", 0) == 0


def test_diff_refs_invalid(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=False, capture_output=True)
    result = _call("diff_refs", {"ref_a": "HEAD", "ref_b": "nonexistent-branch", "path": str(tmp_path)})
    assert isinstance(result, dict)
    assert "error" in result


def test_summarize_diff() -> None:
    raw_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1,3 +1,4 @@\n line1\n-line2\n+line2 changed\n+line3 new\n line3\n"
    result = _call("summarize_diff", {"diff_text": raw_diff})
    assert isinstance(result, dict)
    assert result.get("total_files", 0) == 1
    assert result.get("total_additions", 0) == 2
    assert result.get("total_deletions", 0) == 1


def test_compress_memories_dry_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _call("remember", {"content": "dry-run-test-memory", "scope": "project", "scope_path": tmp})
        result = _call(
            "compress_memories",
            {"summary": "summary", "scope": "project", "scope_path": tmp, "dry_run": True},
        )
        assert isinstance(result, dict)
        assert result.get("dry_run") is True
        assert result.get("would_compress", 0) >= 1
        # Memory should still exist after dry run.
        listed = _call("list_memories", {"scope": "project", "scope_path": tmp})
        assert isinstance(listed, list)
        assert any("dry-run-test-memory" in str(m.get("content", "")) for m in listed if isinstance(m, dict))
        # Clean up.
        for m in listed:
            if isinstance(m, dict) and "dry-run-test-memory" in str(m.get("content", "")):
                _call("forget", {"memory_id": m["id"]})


def test_remember_file_markdown_split() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Header One\n\nContent of section one.\n\n# Header Two\n\nContent of section two.\n")
        tmp_path = f.name

    result = _call("remember_file", {"path": tmp_path, "split_headers": True})
    assert isinstance(result, dict)
    assert result.get("stored", 0) == 2
    memories = result.get("memories", [])
    assert len(memories) == 2
    for m in memories:
        if isinstance(m, dict) and "id" in m:
            _call("forget", {"memory_id": m["id"]})


def test_text_compact_from_text() -> None:
    payload = "\n".join(
        [
            "info: startup complete",
            "2026-05-27T14:00:00Z ERROR TimeoutError while calling https://api.example.dev/v1/items",
            "warning: retrying request",
            "traceback: File \"/srv/app/main.py\", line 42",
        ]
    )
    result = _call("text_compact", {"text": payload, "max_points": 3})
    assert isinstance(result, dict)
    assert result.get("backend") == "deterministic"
    stats = result.get("stats", {})
    assert isinstance(stats, dict)
    assert stats.get("input_lines") == 4
    assert stats.get("selected_lines", 0) >= 1
    patterns = result.get("patterns", [])
    assert isinstance(patterns, list)
    assert any("TimeoutError" == p.get("pattern") for p in patterns if isinstance(p, dict))


def test_text_compact_from_path_with_filters(tmp_path: Path) -> None:
    source = tmp_path / "log.txt"
    source.write_text(
        "\n".join(
            [
                "INFO Connected to /srv/app/config.yaml",
                "ERROR payment failed for order 123",
                "WARN noisy line to skip",
                "ERROR blocked by policy",
            ]
        ),
        encoding="utf-8",
    )
    result = _call(
        "text_compact",
        {
            "path": str(source),
            "mode": "errors-first",
            "include_patterns": ["payment"],
            "exclude_patterns": ["noisy"],
            "max_points": 5,
        },
    )
    assert isinstance(result, dict)
    selected = result.get("selected", [])
    assert isinstance(selected, list)
    assert selected
    assert all("noisy" not in str(item.get("text", "")).lower() for item in selected if isinstance(item, dict))
    assert any("payment" in str(item.get("text", "")).lower() for item in selected if isinstance(item, dict))


def test_apply_text_patch_replace_and_insert(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "edits": [
                {"start_line": 2, "end_line": 2, "content": "beta-updated"},
                {"start_line": 4, "end_line": 3, "content": "delta"},
            ],
        },
    )
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("changed") is True
    assert target.read_text(encoding="utf-8") == "alpha\nbeta-updated\ngamma\ndelta\n"


def test_apply_text_patch_guardrails(tmp_path: Path) -> None:
    missing = _call("apply_text_patch", {"path": str(tmp_path / "missing.txt"), "edits": [{"start_line": 1, "end_line": 0, "content": "x"}]})
    assert isinstance(missing, dict)
    assert "error" in missing

    target = tmp_path / "guard.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    mismatch = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "edits": [{"start_line": 1, "end_line": 1, "content": "ONE"}],
            "expected_hash": "bad-hash",
        },
    )
    assert isinstance(mismatch, dict)
    assert "error" in mismatch

    overlap = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "edits": [
                {"start_line": 1, "end_line": 2, "content": "merged"},
                {"start_line": 2, "end_line": 2, "content": "two"},
            ],
        },
    )
    assert isinstance(overlap, dict)
    assert "error" in overlap


def test_symbol_search_python_symbols(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text(
        "\n".join(
            [
                "VALUE = 1",
                "",
                "class Runner:",
                "    pass",
                "",
                "def run_task(arg: str) -> str:",
                "    return arg",
            ]
        ),
        encoding="utf-8",
    )
    result = _call("symbol_search", {"paths": [str(tmp_path)], "query": "run"})
    assert isinstance(result, dict)
    assert result.get("truncated") is False
    items = result.get("results", [])
    assert isinstance(items, list)
    assert any(item.get("symbol") == "Runner" for item in items if isinstance(item, dict))
    assert any(item.get("symbol") == "run_task" for item in items if isinstance(item, dict))


def test_symbol_search_invalid_kind(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("def ok():\n    return 1\n", encoding="utf-8")
    result = _call("symbol_search", {"paths": [str(target)], "kinds": ["method"]})
    assert isinstance(result, dict)
    assert "error" in result
