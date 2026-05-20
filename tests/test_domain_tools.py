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
