import asyncio
import json
from pathlib import Path

from copilot_fusion.server import create_server
from pytest import MonkeyPatch


def _server(tmp_path: Path, monkeypatch: MonkeyPatch, allowed_commands: list[list[str]]):
    monkeypatch.setenv("FUSION_EXEC_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("FUSION_EXEC_ALLOWLIST", json.dumps(allowed_commands))
    return create_server()


async def _call(server, tool: str, args: dict[str, object]) -> dict[str, object]:
    result = await server.call_tool(tool, args)
    payload = result.structured_content
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]
    assert isinstance(payload, dict)
    return payload


def test_terminal_exec_success_and_failure(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["printf", "ready"], ["false"]])
        success = await _call(server, "terminal_exec", {"command": ["printf", "ready"]})
        assert success["exit_code"] == 0
        assert success["stdout"] == "ready"
        assert success["stderr"] == ""
        assert success["timed_out"] is False

        failure = await _call(server, "terminal_exec", {"command": ["false"]})
        assert failure["exit_code"] != 0

    asyncio.run(run())


def test_terminal_exec_rejects_unapproved_command(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["printf", "ready"]])
        result = await _call(server, "terminal_exec", {"command": ["printf", "different"]})
        assert "allowlist" in str(result["error"]).lower()

    asyncio.run(run())


def test_terminal_exec_timeout(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["sleep", "5"]])
        result = await _call(
            server,
            "terminal_exec",
            {"command": ["sleep", "5"], "timeout_seconds": 0.05},
        )
        assert result["timed_out"] is True
        assert result["exit_code"] is not None

    asyncio.run(run())


def test_terminal_exec_rejects_invalid_directory(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["true"]])
        outside = tmp_path.parent
        result = await _call(
            server,
            "terminal_exec",
            {"command": ["true"], "working_directory": str(outside)},
        )
        assert "inside configured workspace" in str(result["error"])

    asyncio.run(run())


def test_terminal_exec_truncates_output(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["printf", "0123456789"]])
        result = await _call(
            server,
            "terminal_exec",
            {"command": ["printf", "0123456789"], "max_output_chars": 5},
        )
        assert result["stdout"] == "01234"
        assert result["truncated"] is True

    asyncio.run(run())


def test_terminal_process_start_status_and_stop(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["sleep", "5"]])
        started = await _call(server, "terminal_start", {"command": ["sleep", "5"]})
        process_id = str(started["process_id"])

        running = await _call(server, "terminal_status", {"process_id": process_id})
        assert running["state"] == "running"

        stopped = await _call(server, "terminal_stop", {"process_id": process_id})
        assert stopped["state"] == "stopped"
        assert stopped["exit_code"] is not None

    asyncio.run(run())


def test_terminal_exec_blocks_destructive_command(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["rm", "-rf", "target"]])
        result = await _call(server, "terminal_exec", {"command": ["rm", "-rf", "target"]})
        assert "blocked" in str(result["error"])

    asyncio.run(run())
