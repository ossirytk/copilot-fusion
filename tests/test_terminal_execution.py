import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from contextwell_tools.execution import TerminalExecutor, _executable_name, _ProcessRecord
from copilot_fusion.server import create_server
from pytest import MonkeyPatch

SLEEP_COMMAND = [sys.executable, "-c", "import time; time.sleep(5)"]
DIGITS_COMMAND = [sys.executable, "-c", "import sys; sys.stdout.write('0123456789')"]


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
        server = _server(tmp_path, monkeypatch, [["git", "--version"], ["git", "no-such-subcommand"]])
        success = await _call(server, "terminal_exec", {"command": ["git", "--version"]})
        assert success["exit_code"] == 0
        assert str(success["stdout"]).startswith("git version")
        assert success["timed_out"] is False

        failure = await _call(server, "terminal_exec", {"command": ["git", "no-such-subcommand"]})
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
        server = _server(tmp_path, monkeypatch, [SLEEP_COMMAND])
        result = await _call(
            server,
            "terminal_exec",
            {"command": SLEEP_COMMAND, "timeout_seconds": 0.05, "confirm_unsafe": True},
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
        server = _server(tmp_path, monkeypatch, [DIGITS_COMMAND])
        result = await _call(
            server,
            "terminal_exec",
            {"command": DIGITS_COMMAND, "max_output_chars": 5, "confirm_unsafe": True},
        )
        assert result["stdout"] == "01234"
        assert result["truncated"] is True

    asyncio.run(run())


def test_terminal_process_start_status_and_stop(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [SLEEP_COMMAND])
        started = await _call(server, "terminal_start", {"command": SLEEP_COMMAND, "confirm_unsafe": True})
        process_id = str(started["process_id"])

        running = await _call(server, "terminal_status", {"process_id": process_id})
        assert running["state"] == "running"

        stopped = await _call(server, "terminal_stop", {"process_id": process_id})
        assert stopped["state"] == "stopped"
        assert stopped["exit_code"] is not None

    asyncio.run(run())


def test_terminal_exec_blocks_destructive_command(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(
            tmp_path,
            monkeypatch,
            [
                ["rm", "-rf", "target"],
                ["git", "branch", "-D", "topic"],
                ["git", "push", "-d", "origin", "topic"],
                ["git", "push", "-df", "origin", "topic"],
                ["git", "push", "-uon", "origin", "topic"],
                ["git", "stash", "drop", "stash@{0}"],
            ],
        )
        blocked_rm = await _call(server, "terminal_exec", {"command": ["rm", "-rf", "target"]})
        assert "blocked" in str(blocked_rm["error"])

        blocked_branch_delete = await _call(server, "terminal_exec", {"command": ["git", "branch", "-D", "topic"]})
        assert "blocked" in str(blocked_branch_delete["error"])

        blocked_push_delete = await _call(
            server,
            "terminal_exec",
            {"command": ["git", "push", "-d", "origin", "topic"], "confirm_unsafe": True},
        )
        assert "blocked" in str(blocked_push_delete["error"])

        blocked_push_delete_force = await _call(
            server,
            "terminal_exec",
            {"command": ["git", "push", "-df", "origin", "topic"], "confirm_unsafe": True},
        )
        assert "blocked" in str(blocked_push_delete_force["error"])

        blocked_stash_drop = await _call(
            server,
            "terminal_exec",
            {"command": ["git", "stash", "drop", "stash@{0}"], "confirm_unsafe": True},
        )
        assert "blocked" in str(blocked_stash_drop["error"])

        non_destructive_short_flags = await _call(
            server,
            "terminal_exec",
            {"command": ["git", "push", "-uon", "origin", "topic"], "confirm_unsafe": True},
        )
        assert "blocked" not in str(non_destructive_short_flags.get("error", ""))

    asyncio.run(run())


def test_terminal_exec_requires_confirmation_for_unsafe_allowlisted_command(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["python", "-c", "print('ok')"]])
        denied = await _call(server, "terminal_exec", {"command": ["python", "-c", "print('ok')"]})
        assert "confirm_unsafe=true" in str(denied["error"])

        allowed = await _call(
            server,
            "terminal_exec",
            {"command": ["python", "-c", "print('ok')"], "confirm_unsafe": True},
        )
        assert allowed["exit_code"] == 0
        assert allowed["stdout"].strip() == "ok"

    asyncio.run(run())


def test_terminal_exec_requires_confirmation_for_git_switch(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        server = _server(tmp_path, monkeypatch, [["git", "switch", "topic"]])
        denied = await _call(server, "terminal_exec", {"command": ["git", "switch", "topic"]})
        assert "confirm_unsafe=true" in str(denied["error"])

        allowed = await _call(
            server,
            "terminal_exec",
            {"command": ["git", "switch", "topic"], "confirm_unsafe": True},
        )
        assert "error" not in allowed

    asyncio.run(run())


@pytest.mark.skipif(sys.platform == "win32", reason="chmod is POSIX-only")
def test_terminal_exec_requires_confirmation_for_chmod(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    async def run() -> None:
        target = tmp_path / "sample.txt"
        target.write_text("x")
        server = _server(tmp_path, monkeypatch, [["chmod", "644", "sample.txt"]])
        denied = await _call(server, "terminal_exec", {"command": ["chmod", "644", "sample.txt"]})
        assert "confirm_unsafe=true" in str(denied["error"])

        allowed = await _call(
            server,
            "terminal_exec",
            {"command": ["chmod", "644", "sample.txt"], "confirm_unsafe": True},
        )
        assert allowed["exit_code"] == 0

    asyncio.run(run())


def test_terminal_status_does_not_hang_when_readers_never_finish(tmp_path: Path) -> None:
    async def run() -> None:
        executor = TerminalExecutor(tmp_path, {("true",)})
        reader_one = asyncio.create_task(asyncio.sleep(60))
        reader_two = asyncio.create_task(asyncio.sleep(60))
        executor.processes["p"] = _ProcessRecord(
            process_id="p",
            process=SimpleNamespace(returncode=0),
            readers=(reader_one, reader_two),
        )
        try:
            result = await asyncio.wait_for(executor.status("p", max_output_chars=100), timeout=1.0)
        finally:
            reader_one.cancel()
            reader_two.cancel()
            await asyncio.gather(reader_one, reader_two, return_exceptions=True)
        assert result["state"] == "draining"
        assert result["exit_code"] == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("git", "git"),
        ("GIT.EXE", "git"),
        ("C:\\Program Files\\Git\\cmd\\git.exe", "git"),
        ("/usr/bin/python3.12", "python"),
        ("python3", "python"),
        ("powershell.EXE", "powershell"),
        ("rm.exe", "rm"),
        ("pythonista", "pythonista"),
    ],
)
def test_executable_name_normalization(raw: str, expected: str) -> None:
    assert _executable_name(raw) == expected


def test_windows_style_executable_cannot_bypass_policy(tmp_path: Path) -> None:
    executor = TerminalExecutor(tmp_path, {("git.exe", "push", "origin"), ("RM.EXE", "x"), ("cmd.exe", "/c", "dir")})
    assert "confirm_unsafe" in str(executor._validate_command(["git.exe", "push", "origin"], False))
    assert "blocked" in str(executor._validate_command(["RM.EXE", "x"], True))
    assert "confirm_unsafe" in str(executor._validate_command(["cmd.exe", "/c", "dir"], False))
