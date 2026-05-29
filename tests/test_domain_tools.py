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
            'traceback: File "/srv/app/main.py", line 42',
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
        def do_POST(self) -> None:  # noqa: N802
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

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
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
        def do_POST(self) -> None:  # noqa: N802
            body = b"\x80\x81"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
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
        def do_POST(self) -> None:  # noqa: N802
            body = json.dumps({"summary": "auto remote", "bullets": ["one"], "stats": {}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
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


def test_symbol_search_truncation(tmp_path: Path) -> None:
    target = tmp_path / "many.py"
    target.write_text(
        "\n".join(
            [
                "def one():",
                "    return 1",
                "def two():",
                "    return 2",
                "def three():",
                "    return 3",
            ]
        ),
        encoding="utf-8",
    )
    result = _call("symbol_search", {"paths": [str(target)], "max_results": 2})
    assert isinstance(result, dict)
    assert result.get("truncated") is True
    assert len(result.get("results", [])) == 2


def test_symbol_search_javascript_and_typescript(tmp_path: Path) -> None:
    js_file = tmp_path / "mod.js"
    js_file.write_text(
        "\n".join(
            [
                "export function buildClient() { return {}; }",
                "export class Worker {}",
                "const timeoutMs = 1000",
            ]
        ),
        encoding="utf-8",
    )
    ts_file = tmp_path / "mod.ts"
    ts_file.write_text(
        "\n".join(
            [
                "export const runTask = async () => true;",
                "class TaskRunner {}",
            ]
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


def test_symbol_search_references_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "refs.py"
    source.write_text(
        "\n".join(
            [
                "def build_client():",
                "    return 1",
                "",
                "x = build_client()",
                "print(build_client())",
            ]
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
        "\n".join(
            [
                "def compute_value(x):",
                "    return x + 1",
                "",
                "result = compute_value(3)",
                "print(compute_value(4))",
            ]
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
        "\n".join(
            [
                "def helper():",
                "    return 1",
                "",
                "def run():",
                "    return helper()",
                "",
                "value = helper()",
            ]
        ),
        encoding="utf-8",
    )
    js_file = tmp_path / "graph.js"
    js_file.write_text(
        "\n".join(
            [
                "function api() { return 1; }",
                "function main() { return api(); }",
                "const top = api();",
            ]
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
