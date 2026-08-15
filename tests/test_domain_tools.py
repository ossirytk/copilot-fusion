import asyncio
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def _join_lines(*lines: str) -> str:
    return "\n".join(lines)


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
    payload = _join_lines(
        "info: startup complete",
        "2026-05-27T14:00:00Z ERROR TimeoutError while calling https://api.example.dev/v1/items",
        "warning: retrying request",
        'traceback: File "/srv/app/main.py", line 42',
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
        _join_lines(
            "INFO Connected to /srv/app/config.yaml",
            "ERROR payment failed for order 123",
            "WARN noisy line to skip",
            "ERROR blocked by policy",
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


def test_text_compact_from_path_respects_max_bytes(tmp_path: Path) -> None:
    source = tmp_path / "large.log"
    source.write_bytes(b"A" * 1024)
    result = _call("text_compact", {"path": str(source), "max_bytes": 10})
    assert isinstance(result, dict)
    stats = result.get("stats", {})
    assert isinstance(stats, dict)
    assert stats.get("truncated") is True


def test_text_compact_invalid_inputs() -> None:
    empty = _call("text_compact", {})
    assert isinstance(empty, dict)
    assert "error" in empty

    bad_mode = _call("text_compact", {"text": "hello", "mode": "strict"})
    assert isinstance(bad_mode, dict)
    assert "error" in bad_mode

    bad_pattern = _call("text_compact", {"text": "hello", "include_patterns": ["["]})
    assert isinstance(bad_pattern, dict)
    assert "error" in bad_pattern


def test_text_summarize_from_text_and_path(tmp_path: Path) -> None:
    text = (
        "Service started successfully. "
        "The API returned TimeoutError while calling upstream service. "
        "Retry succeeded on second attempt. "
        "Final status is healthy."
    )
    from_text = _call("text_summarize", {"text": text, "max_sentences": 2})
    assert isinstance(from_text, dict)
    assert from_text.get("backend") == "local-extractive"
    assert "TimeoutError" in str(from_text.get("summary", ""))
    stats = from_text.get("stats", {})
    assert isinstance(stats, dict)
    assert stats.get("selected_sentences") == 2

    source = tmp_path / "notes.txt"
    source.write_text(text, encoding="utf-8")
    from_path = _call("text_summarize", {"path": str(source), "backend": "extractive"})
    assert isinstance(from_path, dict)
    assert "summary" in from_path
    assert "error" not in from_path


def test_text_summarize_entity_extraction() -> None:
    text = _join_lines(
        "2026-05-29T18:59:16Z ERROR TimeoutError while calling https://api.example.dev/v1/items",
        'Traceback: File "/srv/app/main.py", line 41',
        "Retrying /srv/app/config.yaml after failure",
    )
    result = _call(
        "text_summarize",
        {"text": text, "backend": "extractive", "include_entities": True, "max_entities": 10},
    )
    assert isinstance(result, dict)
    entities = result.get("entities", [])
    assert isinstance(entities, list)
    assert any(item.get("type") == "url" for item in entities if isinstance(item, dict))
    assert any(item.get("type") == "path" for item in entities if isinstance(item, dict))
    assert any(item.get("type") == "timestamp" for item in entities if isinstance(item, dict))


def test_text_summarize_invalid_inputs() -> None:
    empty = _call("text_summarize", {})
    assert isinstance(empty, dict)
    assert "error" in empty

    invalid = _call("text_summarize", {"text": "hello", "backend": "remote"})
    assert isinstance(invalid, dict)
    assert "error" in invalid


def test_text_summarize_remote_backend(monkeypatch) -> None:
    request_state: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8")
            request_state["payload"] = json.loads(payload)
            request_state["auth"] = self.headers.get("Authorization", "")
            body = json.dumps(
                {
                    "summary": "remote summary",
                    "bullets": ["alpha", "beta"],
                    "stats": {"backend": "remote"},
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("FUSION_TEXT_SUMMARIZER_URL", f"http://127.0.0.1:{server.server_port}/summarize")
        monkeypatch.setenv("FUSION_TEXT_SUMMARIZER_TOKEN", "secret-token")
        result = _call("text_summarize", {"text": "hello world", "backend": "remote", "max_sentences": 2})
        assert isinstance(result, dict)
        assert result.get("backend") == "remote"
        assert result.get("summary") == "remote summary"
        assert result.get("bullets") == ["alpha", "beta"]
        assert request_state.get("payload") == {"text": "hello world", "max_sentences": 2}
        assert request_state.get("auth") == "Bearer secret-token"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_text_summarize_remote_backend_non_utf8(monkeypatch) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = b"\x80\x81"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("FUSION_TEXT_SUMMARIZER_URL", f"http://127.0.0.1:{server.server_port}/summarize")
        result = _call("text_summarize", {"text": "hello world", "backend": "remote"})
        assert isinstance(result, dict)
        assert "error" in result
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_text_summarize_auto_prefers_remote(monkeypatch) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.dumps({"summary": "auto remote", "bullets": ["one"], "stats": {}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("FUSION_TEXT_SUMMARIZER_URL", f"http://127.0.0.1:{server.server_port}/summarize")
        result = _call("text_summarize", {"text": "hello world", "backend": "auto"})
        assert isinstance(result, dict)
        assert result.get("backend") == "remote"
        assert result.get("summary") == "auto remote"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_text_distillation_quality_checks_on_logs() -> None:
    corpus = _join_lines(
        "INFO boot complete",
        "INFO polling upstream service",
        "ERROR TimeoutError while calling https://api.example.dev/v1/items",
        "Traceback (most recent call last):",
        '  File "/srv/app/main.py", line 41, in run',
        "WARN retrying request after timeout",
        "INFO request succeeded on retry",
    )
    compact = _call("text_compact", {"text": corpus, "mode": "errors-first", "max_points": 4})
    summarize = _call("text_summarize", {"text": corpus, "max_sentences": 2})

    assert isinstance(compact, dict)
    compact_selected = " ".join(
        str(item.get("text", "")) for item in compact.get("selected", []) if isinstance(item, dict)
    )
    assert "TimeoutError" in compact_selected
    assert "Traceback" in compact_selected

    assert isinstance(summarize, dict)
    assert "TimeoutError" in str(summarize.get("summary", ""))
    assert summarize.get("backend") == "local-extractive"


def test_text_distillation_quality_checks_on_prose() -> None:
    corpus = _join_lines(
        "The release candidate ships with a smaller bundle and faster startup.",
        "We are deprecating the legacy migration path in favor of the new workflow.",
        "This note contains extra background that should be less important.",
        "The migration guide highlights compatibility and rollout steps.",
    )
    compact = _call("text_compact", {"text": corpus, "max_points": 3, "include_patterns": ["migration", "release"]})
    summarize = _call("text_summarize", {"text": corpus, "max_sentences": 2})

    assert isinstance(compact, dict)
    compact_selected = " ".join(
        str(item.get("text", "")) for item in compact.get("selected", []) if isinstance(item, dict)
    ).lower()
    assert "migration" in compact_selected
    assert "release" in compact_selected

    assert isinstance(summarize, dict)
    summary = str(summarize.get("summary", "")).lower()
    assert "migration" in summary or "release" in summary
    assert len(summarize.get("bullets", [])) <= 2


def test_apply_text_patch_replace_and_insert(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(tmp_path),
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
    missing = _call(
        "apply_text_patch",
        {
            "path": str(tmp_path / "missing.txt"),
            "workspace_root": str(tmp_path),
            "edits": [{"start_line": 1, "end_line": 0, "content": "x"}],
        },
    )
    assert isinstance(missing, dict)
    assert "error" in missing

    target = tmp_path / "guard.txt"
    target.write_text("one\ntwo\n", encoding="utf-8")
    mismatch = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(tmp_path),
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
            "workspace_root": str(tmp_path),
            "edits": [
                {"start_line": 1, "end_line": 2, "content": "merged"},
                {"start_line": 2, "end_line": 2, "content": "two"},
            ],
        },
    )
    assert isinstance(overlap, dict)
    assert "error" in overlap


def test_apply_text_patch_dry_run_and_create(tmp_path: Path) -> None:
    target = tmp_path / "dry.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")

    dry = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(tmp_path),
            "edits": [{"start_line": 2, "end_line": 2, "content": "BETA"}],
            "dry_run": True,
        },
    )
    assert isinstance(dry, dict)
    assert "error" not in dry
    assert dry.get("changed") is True
    preview = dry.get("preview", {})
    assert isinstance(preview, dict)
    assert preview.get("result", {}).get("content") == "alpha\nBETA\n"
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"

    created = tmp_path / "created.txt"
    created_result = _call(
        "apply_text_patch",
        {
            "path": str(created),
            "workspace_root": str(tmp_path),
            "create": True,
            "edits": [{"start_line": 1, "end_line": 0, "content": "first line"}],
        },
    )
    assert isinstance(created_result, dict)
    assert "error" not in created_result
    assert created.read_text(encoding="utf-8") == "first line"

    empty_created = tmp_path / "empty.txt"
    empty_result = _call(
        "apply_text_patch",
        {
            "path": str(empty_created),
            "workspace_root": str(tmp_path),
            "create": True,
            "edits": [{"op": "insert_before", "line": 1, "content": ""}],
        },
    )
    assert isinstance(empty_result, dict)
    assert "error" not in empty_result
    assert empty_created.exists()
    assert empty_created.read_text(encoding="utf-8") == ""


def test_apply_text_patch_operation_modes(tmp_path: Path) -> None:
    target = tmp_path / "ops.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(tmp_path),
            "edits": [
                {"op": "insert_before", "line": 1, "content": "zero"},
                {"op": "delete", "start_line": 2, "end_line": 2},
                {"op": "insert_after", "line": 3, "content": "three-and-half"},
            ],
        },
    )
    assert isinstance(result, dict)
    assert "error" not in result
    normalized = result.get("normalized_edits", [])
    assert isinstance(normalized, list)
    assert any(item.get("op") == "insert_before" for item in normalized if isinstance(item, dict))
    assert any(item.get("op") == "delete" for item in normalized if isinstance(item, dict))
    assert target.read_text(encoding="utf-8") == "zero\none\nthree\nthree-and-half\n"


def test_apply_text_patch_conflict_details(tmp_path: Path) -> None:
    target = tmp_path / "conflict.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")
    result = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(tmp_path),
            "edits": [
                {"op": "replace", "start_line": 1, "end_line": 2, "content": "ab"},
                {"op": "insert_before", "line": 2, "content": "x"},
            ],
        },
    )
    assert isinstance(result, dict)
    assert "error" in result
    details = result.get("details", {})
    assert isinstance(details, dict)
    assert details.get("type") == "insert-range-conflict"


def test_apply_text_patch_workspace_root_policy(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "allowed.txt"
    target.write_text("a\nb\n", encoding="utf-8")

    allowed = _call(
        "apply_text_patch",
        {
            "path": str(target),
            "workspace_root": str(root),
            "edits": [{"start_line": 2, "end_line": 2, "content": "B"}],
        },
    )
    assert isinstance(allowed, dict)
    assert "error" not in allowed
    assert allowed.get("workspace_root") == str(root)

    outside = tmp_path / "outside.txt"
    outside.write_text("x\ny\n", encoding="utf-8")
    denied = _call(
        "apply_text_patch",
        {
            "path": str(outside),
            "workspace_root": str(root),
            "edits": [{"start_line": 1, "end_line": 1, "content": "X"}],
        },
    )
    assert isinstance(denied, dict)
    assert "error" in denied
    details = denied.get("details", {})
    assert isinstance(details, dict)
    assert details.get("type") == "path-outside-root"


def test_apply_text_patch_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "sub").mkdir()
    target = root / "sub" / "file.txt"
    target.write_text("hello\nworld\n", encoding="utf-8")

    result = _call(
        "apply_text_patch",
        {
            "path": "sub/file.txt",
            "workspace_root": str(root),
            "edits": [{"start_line": 1, "end_line": 1, "content": "HELLO"}],
        },
    )
    assert isinstance(result, dict)
    assert "error" not in result
    assert target.read_text(encoding="utf-8") == "HELLO\nworld\n"


def test_apply_text_patch_batch_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    first = root / "a.txt"
    first.write_text("x\n", encoding="utf-8")

    result = _call(
        "apply_text_patch_batch",
        {
            "workspace_root": str(root),
            "patches": [
                {
                    "path": "a.txt",
                    "edits": [{"start_line": 1, "end_line": 1, "content": "X"}],
                }
            ],
        },
    )
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("applied") == 1
    assert first.read_text(encoding="utf-8") == "X\n"


def test_symbol_search_invalid_kind_message(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text("def run():\n    pass\n", encoding="utf-8")
    for bad_kind in ("fn", "enum", "variant"):
        result = _call("symbol_search", {"paths": [str(target)], "kinds": [bad_kind]})
        assert isinstance(result, dict)
        assert "error" in result
        assert "function" in result["error"]
        assert "class" in result["error"]
        assert "variable" in result["error"]


def test_apply_text_patch_workspace_root_required(tmp_path: Path) -> None:
    target = tmp_path / "required.txt"
    target.write_text("a\n", encoding="utf-8")
    result = _call(
        "apply_text_patch",
        {"path": str(target), "edits": [{"start_line": 1, "end_line": 1, "content": "A"}]},
    )
    assert isinstance(result, dict)
    assert "error" in result
    details = result.get("details", {})
    assert isinstance(details, dict)
    assert details.get("type") == "workspace-root-required"


def test_apply_text_patch_batch(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    first = root / "first.txt"
    first.write_text("alpha\nbeta\n", encoding="utf-8")
    second = root / "second.txt"
    second.write_text("one\ntwo\n", encoding="utf-8")

    result = _call(
        "apply_text_patch_batch",
        {
            "workspace_root": str(root),
            "patches": [
                {
                    "path": str(first),
                    "edits": [{"start_line": 2, "end_line": 2, "content": "BETA"}],
                },
                {
                    "path": str(second),
                    "edits": [{"start_line": 1, "end_line": 1, "content": "ONE"}],
                },
            ],
        },
    )
    assert isinstance(result, dict)
    assert "error" not in result
    assert result.get("applied") == 2
    assert result.get("changed") == 2
    assert first.read_text(encoding="utf-8") == "alpha\nBETA\n"
    assert second.read_text(encoding="utf-8") == "ONE\ntwo\n"


def test_symbol_search_python_symbols(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text(
        _join_lines(
            "VALUE = 1",
            "",
            "class Runner:",
            "    pass",
            "",
            "def run_task(arg: str) -> str:",
            "    return arg",
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


def test_symbol_search_truncation(tmp_path: Path) -> None:
    target = tmp_path / "many.py"
    target.write_text(
        _join_lines(
            "def one():",
            "    return 1",
            "def two():",
            "    return 2",
            "def three():",
            "    return 3",
        ),
        encoding="utf-8",
    )
    result = _call("symbol_search", {"paths": [str(target)], "max_results": 2})
    assert isinstance(result, dict)
    assert result.get("truncated") is True
    assert len(result.get("results", [])) == 2


def test_symbol_search_cache_invalidation(tmp_path: Path) -> None:
    target = tmp_path / "cached.py"
    target.write_text("def alpha():\n    return 1\n", encoding="utf-8")

    first = _call("symbol_search", {"paths": [str(target)], "query": "alpha", "kinds": ["function"]})
    assert isinstance(first, dict)
    assert any(item.get("symbol") == "alpha" for item in first.get("results", []) if isinstance(item, dict))

    target.write_text("def beta():\n    return 2\n# cache-bust\n", encoding="utf-8")

    second = _call("symbol_search", {"paths": [str(target)], "query": "beta", "kinds": ["function"]})
    assert isinstance(second, dict)
    assert any(item.get("symbol") == "beta" for item in second.get("results", []) if isinstance(item, dict))


def test_symbol_search_javascript_and_typescript(tmp_path: Path) -> None:
    js_file = tmp_path / "mod.js"
    js_file.write_text(
        _join_lines(
            "export function buildClient() { return {}; }",
            "export class Worker {}",
            "const timeoutMs = 1000",
        ),
        encoding="utf-8",
    )
    jsx_file = tmp_path / "view.jsx"
    jsx_file.write_text(
        _join_lines(
            "export function RenderView() { return <div />; }",
            "export const jsxValue = 1;",
        ),
        encoding="utf-8",
    )
    ts_file = tmp_path / "mod.ts"
    ts_file.write_text(
        _join_lines(
            "export const runTask = async () => true;",
            "class TaskRunner {}",
        ),
        encoding="utf-8",
    )
    tsx_file = tmp_path / "panel.tsx"
    tsx_file.write_text(
        _join_lines(
            "export function RenderPanel() { return <section />; }",
            "const tsxValue = 2;",
        ),
        encoding="utf-8",
    )

    result = _call("symbol_search", {"paths": [str(tmp_path)], "query": "task"})
    assert isinstance(result, dict)
    assert "error" not in result
    rows = result.get("results", [])
    assert isinstance(rows, list)
    assert any(item.get("symbol") == "runTask" for item in rows if isinstance(item, dict))
    assert any(item.get("language") == "typescript" for item in rows if isinstance(item, dict))

    jsx_result = _call("symbol_search", {"paths": [str(tmp_path)], "query": "render"})
    assert isinstance(jsx_result, dict)
    jsx_rows = jsx_result.get("results", [])
    assert isinstance(jsx_rows, list)
    assert any(item.get("symbol") == "RenderView" for item in jsx_rows if isinstance(item, dict))
    assert any(item.get("symbol") == "RenderPanel" for item in jsx_rows if isinstance(item, dict))


def test_symbol_search_references_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "refs.py"
    source.write_text(
        _join_lines(
            "def build_client():",
            "    return 1",
            "",
            "x = build_client()",
            "print(build_client())",
        ),
        encoding="utf-8",
    )
    result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "build_client",
            "kinds": ["function"],
            "include_references": True,
            "max_references_per_symbol": 2,
        },
    )
    assert isinstance(result, dict)
    rows = result.get("results", [])
    assert isinstance(rows, list)
    assert rows
    function_row = rows[0]
    assert function_row.get("column", 0) >= 1
    assert "indent" in function_row
    refs = function_row.get("references", {})
    assert isinstance(refs, dict)
    assert refs.get("count", 0) >= 1
    assert isinstance(refs.get("items", []), list)


def test_symbol_search_callsites(tmp_path: Path) -> None:
    source = tmp_path / "calls.py"
    source.write_text(
        _join_lines(
            "def compute_value(x):",
            "    return x + 1",
            "",
            "result = compute_value(3)",
            "print(compute_value(4))",
        ),
        encoding="utf-8",
    )
    result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "compute_value",
            "kinds": ["function"],
            "include_references": True,
            "include_callsites": True,
            "max_references_per_symbol": 5,
        },
    )
    assert isinstance(result, dict)
    rows = result.get("results", [])
    assert isinstance(rows, list)
    assert rows
    refs = rows[0].get("references", {})
    assert isinstance(refs, dict)
    assert refs.get("callsite_count", 0) >= 1
    items = refs.get("items", [])
    assert isinstance(items, list)
    assert any(item.get("match_type") == "callsite" for item in items if isinstance(item, dict))


def test_symbol_search_callgraph(tmp_path: Path) -> None:
    py_file = tmp_path / "graph.py"
    py_file.write_text(
        _join_lines(
            "def helper():",
            "    return 1",
            "",
            "def run():",
            "    return helper()",
            "",
            "value = helper()",
        ),
        encoding="utf-8",
    )
    js_file = tmp_path / "graph.js"
    js_file.write_text(
        _join_lines(
            "function api() { return 1; }",
            "function main() { return api(); }",
            "const top = api();",
        ),
        encoding="utf-8",
    )
    py_result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "helper",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(py_result, dict)
    py_rows = py_result.get("results", [])
    assert isinstance(py_rows, list)
    py_target = next((row for row in py_rows if isinstance(row, dict) and row.get("symbol") == "helper"), None)
    assert isinstance(py_target, dict)
    py_graph = py_target.get("callgraph", {})
    assert isinstance(py_graph, dict)
    assert "run" in py_graph.get("callers", [])

    py_run_result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "run",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(py_run_result, dict)
    py_run_rows = py_run_result.get("results", [])
    assert isinstance(py_run_rows, list)
    py_run_target = next((row for row in py_run_rows if isinstance(row, dict) and row.get("symbol") == "run"), None)
    assert isinstance(py_run_target, dict)
    py_run_graph = py_run_target.get("callgraph", {})
    assert isinstance(py_run_graph, dict)
    assert any(item.get("symbol") == "helper" for item in py_run_graph.get("callees", []) if isinstance(item, dict))

    js_result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "api",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(js_result, dict)
    js_rows = js_result.get("results", [])
    assert isinstance(js_rows, list)
    js_target = next((row for row in js_rows if isinstance(row, dict) and row.get("symbol") == "api"), None)
    assert isinstance(js_target, dict)
    js_graph = js_target.get("callgraph", {})
    assert isinstance(js_graph, dict)
    assert "main" in js_graph.get("callers", [])

    js_main_result = _call(
        "symbol_search",
        {
            "paths": [str(tmp_path)],
            "query": "main",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(js_main_result, dict)
    js_main_rows = js_main_result.get("results", [])
    assert isinstance(js_main_rows, list)
    js_main_target = next((row for row in js_main_rows if isinstance(row, dict) and row.get("symbol") == "main"), None)
    assert isinstance(js_main_target, dict)
    js_main_graph = js_main_target.get("callgraph", {})
    assert isinstance(js_main_graph, dict)
    assert any(item.get("symbol") == "api" for item in js_main_graph.get("callees", []) if isinstance(item, dict))

    js_quirks = tmp_path / "quirks.js"
    js_quirks.write_text(
        _join_lines(
            'function outer() { const msg = "use { brace }"; return msg; }',
            "const topLevel = helper();",
            "function helper() { return 1; }",
        ),
        encoding="utf-8",
    )
    quirks_result = _call(
        "symbol_search",
        {
            "paths": [str(js_quirks)],
            "query": "helper",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(quirks_result, dict)
    quirks_rows = quirks_result.get("results", [])
    assert isinstance(quirks_rows, list)
    quirks_target = next((row for row in quirks_rows if isinstance(row, dict) and row.get("symbol") == "helper"), None)
    assert isinstance(quirks_target, dict)
    quirks_graph = quirks_target.get("callgraph", {})
    assert isinstance(quirks_graph, dict)
    assert "<module>" in quirks_graph.get("callers", [])

    js_regex = tmp_path / "regex.js"
    js_regex.write_text(
        _join_lines(
            "function compute() {",
            "  const r = /pattern}/;",
            "  return helper();",
            "}",
            "function helper() { return 1; }",
        ),
        encoding="utf-8",
    )
    regex_result = _call(
        "symbol_search",
        {
            "paths": [str(js_regex)],
            "query": "compute",
            "kinds": ["function"],
            "include_callgraph": True,
        },
    )
    assert isinstance(regex_result, dict)
    regex_rows = regex_result.get("results", [])
    assert isinstance(regex_rows, list)
    regex_target = next((row for row in regex_rows if isinstance(row, dict) and row.get("symbol") == "compute"), None)
    assert isinstance(regex_target, dict)
    regex_graph = regex_target.get("callgraph", {})
    assert isinstance(regex_graph, dict)
    assert any(item.get("symbol") == "helper" for item in regex_graph.get("callees", []) if isinstance(item, dict))
