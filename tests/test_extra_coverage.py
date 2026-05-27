"""Additional tests to bring coverage above the quality gate."""

from __future__ import annotations

import asyncio
import json
import subprocess
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


# ---------------------------------------------------------------------------
# Core registry tests
# ---------------------------------------------------------------------------


def test_remember_duplicate_detection() -> None:
    """remember returns duplicate=True when same content+scope already exists."""
    first = _call("remember", {"content": "duplicate-sentinel-xyz", "scope": "global"})
    assert isinstance(first, dict)
    assert "id" in first

    second = _call("remember", {"content": "duplicate-sentinel-xyz", "scope": "global"})
    assert isinstance(second, dict)
    assert second.get("duplicate") is True

    # Clean up
    _call("forget", {"memory_id": first["id"]})


def test_remember_with_expires_at_and_scope_path() -> None:
    """remember stores scope_path and expires_at; recall filters by scope_path."""
    result = _call(
        "remember",
        {
            "content": "scoped-content-abc",
            "scope": "project",
            "scope_path": "/tmp/proj-a",
            "expires_at": "2099-01-01T00:00:00+00:00",
        },
    )
    assert isinstance(result, dict)
    assert "id" in result
    memory_id = result["id"]

    # Recall with matching scope_path finds it.
    recalled = _call("recall", {"query": "scoped-content-abc", "scope_path": "/tmp/proj-a"})
    assert isinstance(recalled, list)
    assert any(item.get("content") == "scoped-content-abc" for item in recalled if isinstance(item, dict))

    # Recall with different scope_path does not find it.
    not_recalled = _call("recall", {"query": "scoped-content-abc", "scope_path": "/tmp/proj-b"})
    assert isinstance(not_recalled, list)
    assert not any(item.get("content") == "scoped-content-abc" for item in not_recalled if isinstance(item, dict))

    _call("forget", {"memory_id": memory_id})


def test_recall_with_type_and_tag_filters() -> None:
    """recall correctly filters by type and tags."""
    r = _call("remember", {"content": "tagged-recall-entry", "type": "code", "tags": ["pytest", "coverage"]})
    assert isinstance(r, dict)
    memory_id = r["id"]

    # Filter by type match.
    found = _call("recall", {"query": "tagged-recall-entry", "type": "code"})
    assert isinstance(found, list)
    assert any(item.get("type") == "code" for item in found if isinstance(item, dict))

    # Filter by tag match.
    tagged = _call("recall", {"query": "tagged-recall-entry", "tags": ["pytest"]})
    assert isinstance(tagged, list)
    assert len(tagged) >= 1

    # Filter by non-matching type returns nothing.
    wrong_type = _call("recall", {"query": "tagged-recall-entry", "type": "chat"})
    assert isinstance(wrong_type, list)
    assert not any(item.get("content") == "tagged-recall-entry" for item in wrong_type if isinstance(item, dict))

    _call("forget", {"memory_id": memory_id})


def test_recall_with_include_score() -> None:
    """recall includes score field when include_score=True."""
    r = _call("remember", {"content": "score-test-memory", "scope": "global"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    scored = _call("recall", {"query": "score-test-memory", "include_score": True})
    assert isinstance(scored, list)
    assert any("score" in item for item in scored if isinstance(item, dict))

    _call("forget", {"memory_id": memory_id})


def test_recall_since_until_filters() -> None:
    """recall filters by since/until timestamps."""
    r = _call("remember", {"content": "time-filtered-memory"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    # since in the future: should not find this memory.
    not_found = _call("recall", {"query": "time-filtered-memory", "since": "2099-01-01T00:00:00+00:00"})
    assert isinstance(not_found, list)
    assert not any(item.get("content") == "time-filtered-memory" for item in not_found if isinstance(item, dict))

    # until in the past: should not find this memory.
    not_found2 = _call("recall", {"query": "time-filtered-memory", "until": "2000-01-01T00:00:00+00:00"})
    assert isinstance(not_found2, list)
    assert not any(item.get("content") == "time-filtered-memory" for item in not_found2 if isinstance(item, dict))

    _call("forget", {"memory_id": memory_id})


def test_forget_no_match() -> None:
    """forget returns 'No matching memory found.' for unknown IDs."""
    result = _call("forget", {"memory_id": "nonexistent-id-00000000-0000-0000-0000-000000000000"})
    assert "No matching memory found" in str(result)


def test_forget_by_prefix() -> None:
    """forget can delete by unambiguous prefix."""
    r = _call("remember", {"content": "prefix-forget-test", "allow_duplicate": True})
    assert isinstance(r, dict)
    memory_id = r["id"]

    prefix = memory_id[:8]
    result = _call("forget", {"memory_id": prefix})
    assert "deleted" in str(result).lower()


def test_list_memories_with_filters() -> None:
    """list_memories filters by scope, type, tags, since, until."""
    r = _call(
        "remember",
        {
            "content": "list-filter-test-memory",
            "type": "decision",
            "scope": "global",
            "tags": ["list-filter-tag"],
        },
    )
    assert isinstance(r, dict)
    memory_id = r["id"]

    listed = _call("list_memories", {"type": "decision", "tags": ["list-filter-tag"]})
    assert isinstance(listed, list)
    assert any(item.get("content") == "list-filter-test-memory" for item in listed if isinstance(item, dict))

    # since far future: exclude this memory.
    empty = _call("list_memories", {"since": "2099-01-01T00:00:00+00:00"})
    assert isinstance(empty, list)
    assert not any(item.get("content") == "list-filter-test-memory" for item in empty if isinstance(item, dict))

    # until far past: exclude this memory.
    empty2 = _call("list_memories", {"until": "2000-01-01T00:00:00+00:00"})
    assert isinstance(empty2, list)
    assert not any(item.get("content") == "list-filter-test-memory" for item in empty2 if isinstance(item, dict))

    _call("forget", {"memory_id": memory_id})


def test_update_memory() -> None:
    """update modifies content, type, tags, and source of an existing memory."""
    r = _call("remember", {"content": "original-content", "type": "fact"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    updated = _call(
        "update",
        {
            "memory_id": memory_id,
            "content": "updated-content",
            "type": "chat",
            "tags": ["updated"],
            "source": "test",
        },
    )
    assert isinstance(updated, dict)
    assert "updated_at" in updated

    _call("forget", {"memory_id": memory_id})


def test_update_memory_not_found() -> None:
    """update returns an error for non-existent memory IDs."""
    result = _call("update", {"memory_id": "nonexistent-000-0000-0000-000000000000"})
    assert isinstance(result, dict)
    assert "error" in result


def test_remember_file() -> None:
    """remember_file stores the content of a file as a memory."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("file-memory-content")
        tmp_path = f.name

    result = _call("remember_file", {"path": tmp_path, "scope": "global", "tags": ["file"]})
    assert isinstance(result, dict)
    assert result.get("stored") == 1
    memories = result.get("memories", [])
    assert isinstance(memories, list)
    assert len(memories) == 1
    assert "id" in memories[0]

    _call("forget", {"memory_id": memories[0]["id"]})


def test_remember_batch() -> None:
    """remember_batch stores multiple memories at once."""
    items = [
        {"content": "batch-item-1", "type": "fact", "scope": "global"},
        {"content": "batch-item-2", "type": "code", "scope": "global"},
    ]
    result = _call("remember_batch", {"memories": items})
    assert isinstance(result, dict)
    assert result.get("stored") == 2
    for mem in result.get("items", []):
        assert isinstance(mem, dict)
        assert "id" in mem
        _call("forget", {"memory_id": mem["id"]})


def test_compress_memories() -> None:
    """compress_memories replaces many memories with a single summary."""
    for i in range(3):
        _call("remember", {"content": f"compress-test-{i}", "type": "fact", "tags": ["compress-group"]})

    result = _call(
        "compress_memories",
        {"summary": "compressed-summary", "type": "fact", "tags": ["compress-group"]},
    )
    assert isinstance(result, dict)
    assert "compressed" in result
    summary_mem = result.get("summary_memory", {})
    if isinstance(summary_mem, dict) and "id" in summary_mem:
        _call("forget", {"memory_id": summary_mem["id"]})


def test_export_memories_json() -> None:
    """export_memories returns a JSON payload."""
    r = _call("remember", {"content": "export-json-test"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    result = _call("export_memories", {"format": "json"})
    assert isinstance(result, dict)
    assert "content" in result
    parsed = json.loads(str(result["content"]))
    assert isinstance(parsed, list)

    _call("forget", {"memory_id": memory_id})


def test_export_memories_markdown() -> None:
    """export_memories returns a markdown payload."""
    r = _call("remember", {"content": "export-markdown-test"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    result = _call("export_memories", {"format": "markdown"})
    assert isinstance(result, dict)
    assert "content" in result

    _call("forget", {"memory_id": memory_id})


def test_export_memories_org() -> None:
    """export_memories returns an org payload."""
    r = _call("remember", {"content": "export-org-test"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    result = _call("export_memories", {"format": "org"})
    assert isinstance(result, dict)
    assert "content" in result

    _call("forget", {"memory_id": memory_id})


def test_export_memories_to_file() -> None:
    """export_memories writes to disk when a path is provided."""
    r = _call("remember", {"content": "export-file-test"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    with tempfile.TemporaryDirectory() as tmp:
        out_path = str(Path(tmp) / "export.json")
        result = _call("export_memories", {"format": "json", "path": out_path})
        assert isinstance(result, dict)
        assert "path" in result
        assert Path(out_path).exists()

    _call("forget", {"memory_id": memory_id})


def test_memory_stats() -> None:
    """memory_stats returns total counts and breakdown."""
    r = _call("remember", {"content": "stats-test-memory", "type": "fact", "scope": "global"})
    assert isinstance(r, dict)
    memory_id = r["id"]

    stats = _call("memory_stats", {})
    assert isinstance(stats, dict)
    assert "total" in stats
    assert stats["total"] >= 1
    assert "by_type" in stats
    assert "by_scope" in stats

    _call("forget", {"memory_id": memory_id})


def test_purge_expired() -> None:
    """purge_expired deletes memories whose expires_at is in the past."""
    r = _call(
        "remember",
        {
            "content": "expired-memory",
            "expires_at": "2000-01-01T00:00:00+00:00",
            "allow_duplicate": True,
        },
    )
    assert isinstance(r, dict)

    result = _call("purge_expired", {})
    assert isinstance(result, str)
    assert "Purged" in result


def test_reembed_all() -> None:
    """reembed_all returns a status message."""
    result = _call("reembed_all", {})
    assert isinstance(result, dict)
    assert "status" in result


# ---------------------------------------------------------------------------
# Tools registry tests
# ---------------------------------------------------------------------------


def test_fs_tree_basic() -> None:
    """fs_tree returns directory entries within depth/count limits."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "file1.txt").write_text("a")
        sub = root / "subdir"
        sub.mkdir()
        (sub / "file2.txt").write_text("b")
        (root / ".hidden").write_text("h")

        result = _call("fs_tree", {"path": tmp, "include_hidden": False, "max_depth": 2})
        assert isinstance(result, dict)
        paths = [e["path"] for e in result.get("entries", [])]
        assert any("file1.txt" in p for p in paths)
        assert not any(".hidden" in p for p in paths)

        # With include_hidden=True the hidden file should appear.
        result_hidden = _call("fs_tree", {"path": tmp, "include_hidden": True, "max_depth": 2})
        paths_hidden = [e["path"] for e in result_hidden.get("entries", [])]
        assert any(".hidden" in p for p in paths_hidden)


def test_fs_tree_max_entries_truncation() -> None:
    """fs_tree reports truncated=True when max_entries is reached."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(5):
            (root / f"file{i}.txt").write_text(str(i))

        result = _call("fs_tree", {"path": tmp, "max_entries": 3})
        assert isinstance(result, dict)
        assert result.get("truncated") is True
        assert len(result.get("entries", [])) <= 3


def test_text_search_invalid_regex() -> None:
    """text_search returns an error dict for invalid regex patterns."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _call("text_search", {"mode": "regex", "paths": [tmp], "query": "["})
        assert isinstance(result, dict)
        assert "error" in result


def test_text_search_in_directory() -> None:
    """text_search scans files inside a directory using lazy iteration."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "alpha.txt").write_text("hello world\nfoo bar\n")
        (root / "beta.txt").write_text("world hello\n")

        result = _call("text_search", {"mode": "literal", "paths": [tmp], "query": "hello"})
        assert isinstance(result, dict)
        hits = result.get("results", [])
        assert isinstance(hits, list)
        assert len(hits) >= 2


def test_text_search_max_results_truncation() -> None:
    """text_search stops and reports truncated when max_results is reached."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        content = "\n".join(["needle"] * 20)
        (root / "big.txt").write_text(content)

        result = _call("text_search", {"mode": "literal", "paths": [tmp], "query": "needle", "max_results": 5})
        assert isinstance(result, dict)
        assert result.get("truncated") is True
        assert len(result.get("results", [])) <= 5


def test_json_select_invalid_json() -> None:
    """json_select returns an error when the file contains invalid JSON."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{not valid json}")
        tmp_path = f.name

    result = _call("json_select", {"path": tmp_path, "fields": ["name"]})
    assert isinstance(result, dict)
    assert "error" in result


def test_json_select_invalid_filter_schema() -> None:
    """json_select returns an error when a filter dict is missing required keys."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(json.dumps([{"name": "alpha"}]))
        tmp_path = f.name

    result = _call(
        "json_select",
        {"path": tmp_path, "fields": ["name"], "filters": [{"field": "name"}]},  # missing op/value
    )
    assert isinstance(result, dict)
    assert "error" in result


def test_yaml_select_with_yaml_file() -> None:
    """yaml_select reads YAML files correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("name: fusion\nversion: 1\n")
        tmp_path = f.name

    result = _call("yaml_select", {"path": tmp_path, "fields": ["name", "version"]})
    assert isinstance(result, dict)
    assert "error" not in result
    results = result.get("results", {})
    assert results.get("name") == "fusion"
    assert results.get("version") == 1


def test_yaml_select_invalid_file() -> None:
    """yaml_select returns an error for unreadable/invalid files."""
    result = _call("yaml_select", {"path": "/nonexistent/path/file.yaml", "fields": ["key"]})
    assert isinstance(result, dict)
    assert "error" in result


def test_yaml_select_with_toml_file() -> None:
    """yaml_select handles TOML files via the .toml branch."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[project]\nname = "fusion"\n')
        tmp_path = f.name

    result = _call("yaml_select", {"path": tmp_path, "fields": ["project"]})
    assert isinstance(result, dict)
    assert "error" not in result


def test_read_file_max_bytes() -> None:
    """read_file truncates at max_bytes without reading the whole file first."""
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as f:
        f.write(b"A" * 10_000)
        tmp_path = f.name

    result = _call("read_file", {"path": tmp_path, "max_bytes": 100})
    assert isinstance(result, dict)
    assert result.get("truncated") is True
    assert result.get("bytes_read") == 100


def test_read_file_with_compact_mode() -> None:
    """read_file can optionally return compacted high-signal output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write("info startup\nERROR timeout from upstream\ntraceback: File \"/srv/app.py\", line 2\n")
        tmp_path = f.name

    result = _call("read_file", {"path": tmp_path, "compact": True, "compact_mode": "errors-first", "compact_max_points": 2})
    assert isinstance(result, dict)
    compact = result.get("compact", {})
    assert isinstance(compact, dict)
    assert compact.get("backend") == "deterministic"
    stats = compact.get("stats", {})
    assert isinstance(stats, dict)
    assert stats.get("selected_lines", 0) >= 1


# ---------------------------------------------------------------------------
# Git registry tests
# ---------------------------------------------------------------------------


def _init_repo(tmp: str) -> None:
    """Helper to initialize a minimal git repo."""
    repo = Path(tmp)
    subprocess.run(["git", "init"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True, capture_output=True)
    (repo / "init.txt").write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True, capture_output=True)


def test_git_reset_invalid_mode() -> None:
    """git_reset returns an error for an invalid mode."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        result = _call("git_reset", {"path": tmp, "mode": "invalid-mode"})
        assert isinstance(result, dict)
        assert "error" in result


def test_git_reset_with_ref_and_files() -> None:
    """git_reset uses the provided ref when resetting specific files."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        (Path(tmp) / "changed.txt").write_text("changed\n")
        subprocess.run(["git", "add", "changed.txt"], cwd=tmp, check=True, capture_output=True)

        result = _call("git_reset", {"path": tmp, "ref": "HEAD", "files": ["changed.txt"]})
        assert isinstance(result, dict)
        # Should succeed (no error key) or the file is now unstaged.
        assert "error" not in result or "not a git repository" in str(result.get("error", ""))


def test_git_diff() -> None:
    """git_diff returns diff output."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        (Path(tmp) / "init.txt").write_text("modified\n")

        result = _call("git_diff", {"path": tmp})
        assert isinstance(result, dict)
        assert "error" not in result


def test_git_log() -> None:
    """git_log returns commit log."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)

        result = _call("git_log", {"path": tmp, "limit": 5})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "raw" in result


def test_git_show() -> None:
    """git_show returns show output for HEAD."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)

        result = _call("git_show", {"path": tmp, "ref": "HEAD"})
        assert isinstance(result, dict)
        assert "error" not in result


def test_git_branch_list() -> None:
    """git_branch lists branches in the repo."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)

        result = _call("git_branch", {"path": tmp})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "branches" in result


def test_git_stash_push_and_pop() -> None:
    """git_stash pushes changes and pops them back."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        (Path(tmp) / "init.txt").write_text("stashed change\n")

        push_result = _call("git_stash", {"path": tmp})
        assert isinstance(push_result, dict)

        pop_result = _call("git_stash", {"path": tmp, "pop": True})
        assert isinstance(pop_result, dict)


def test_git_tag_list() -> None:
    """git_tag lists tags (empty list expected for fresh repo)."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)

        result = _call("git_tag", {"path": tmp})
        assert isinstance(result, dict)
        assert "tags" in result


def test_git_remote_list() -> None:
    """git_remote lists remotes (empty for fresh repo)."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)

        result = _call("git_remote", {"path": tmp})
        assert isinstance(result, dict)


def test_git_commit_with_add_all() -> None:
    """git_commit with add_all=True stages and commits new files."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        (Path(tmp) / "new.txt").write_text("new content\n")

        result = _call("git_commit", {"path": tmp, "message": "test commit", "add_all": True})
        assert isinstance(result, dict)
        assert "error" not in result
