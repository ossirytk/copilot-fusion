"""Controlled terminal execution tools."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import FastMCP

_DEFAULT_OUTPUT_LIMIT = 8_000
_MAX_OUTPUT_LIMIT = 20_000
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_PROCESSES = 100
_RECORD_OUTPUT_BYTES = _MAX_OUTPUT_LIMIT
_BLOCKED_EXECUTABLES = {
    "dd",
    "fdisk",
    "format",
    "halt",
    "chmod",
    "chown",
    "kill",
    "killall",
    "mkfs",
    "mount",
    "parted",
    "poweroff",
    "reboot",
    "rm",
    "rmdir",
    "shred",
    "shutdown",
    "sudo",
    "su",
    "truncate",
    "umount",
    "unlink",
}


@dataclass(slots=True)
class _ProcessRecord:
    process_id: str
    process: asyncio.subprocess.Process
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    readers: tuple[asyncio.Task[None], asyncio.Task[None]] | None = None


class TerminalExecutor:
    """Run explicitly approved commands within a configured workspace."""

    def __init__(self, workspace: Path, allowlist: set[tuple[str, ...]]) -> None:
        self.workspace = workspace
        self.allowlist = allowlist
        self.processes: dict[str, _ProcessRecord] = {}
        self._start_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> TerminalExecutor:
        workspace_setting = os.getenv("FUSION_EXEC_WORKSPACE")
        workspace = Path(workspace_setting or Path.cwd()).expanduser().resolve()
        if not workspace.is_dir():
            raise ValueError(f"FUSION_EXEC_WORKSPACE is not a directory: {workspace}")

        allowlist_setting = os.getenv("FUSION_EXEC_ALLOWLIST", "[]")
        try:
            raw_allowlist = json.loads(allowlist_setting)
        except json.JSONDecodeError as exc:
            raise ValueError("FUSION_EXEC_ALLOWLIST must be a JSON array of argv arrays") from exc
        if not isinstance(raw_allowlist, list):
            raise ValueError("FUSION_EXEC_ALLOWLIST must be a JSON array of argv arrays")

        allowlist: set[tuple[str, ...]] = set()
        for entry in raw_allowlist:
            if (
                not isinstance(entry, list)
                or not entry
                or not isinstance(entry[0], str)
                or not entry[0]
                or any(not isinstance(part, str) or "\0" in part for part in entry)
            ):
                raise ValueError("Each FUSION_EXEC_ALLOWLIST entry must be an argv array with a non-empty executable")
            allowlist.add(tuple(entry))
        return cls(workspace, allowlist)

    def _validate_command(self, command: list[str]) -> str | None:
        if (
            not command
            or not isinstance(command[0], str)
            or not command[0]
            or any(not isinstance(part, str) or "\0" in part for part in command)
        ):
            return "command must be an argv array with a non-empty executable"
        if tuple(command) not in self.allowlist:
            return "command is not in FUSION_EXEC_ALLOWLIST"

        executable = Path(command[0]).name.lower()
        if executable in _BLOCKED_EXECUTABLES:
            return f"destructive or privileged executable is blocked: {executable}"
        if executable == "git" and len(command) > 1:
            subcommand = command[1].lower()
            args = {arg.lower() for arg in command[2:]}
            if subcommand in {"checkout", "reset", "restore", "switch"}:
                return "destructive git command is blocked"
            if subcommand == "clean" and any(arg.startswith("-") and "f" in arg[1:] for arg in args):
                return "destructive git command is blocked"
            if subcommand == "stash" and args & {"drop", "clear"}:
                return "destructive git command is blocked"
            if subcommand == "branch" and "-d" in args:
                return "branch deletion is blocked"
            if subcommand == "push" and any(
                arg.lower() in {"--force", "-f", "--delete"} or arg.lower().startswith("--force-")
                for arg in command[2:]
            ):
                return "destructive push is blocked"
        return None

    def _resolve_working_directory(self, working_directory: str | None) -> Path | str:
        candidate = Path(working_directory).expanduser() if working_directory else self.workspace
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.workspace):
            return f"working directory must be inside configured workspace: {self.workspace}"
        if not resolved.is_dir():
            return f"working directory is not a directory: {resolved}"
        return resolved

    async def _read_stream(self, stream: asyncio.StreamReader, buffer: bytearray, record: _ProcessRecord) -> None:
        truncated_attr = "stdout_truncated" if buffer is record.stdout else "stderr_truncated"
        while chunk := await stream.read(4096):
            remaining = _RECORD_OUTPUT_BYTES - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                setattr(record, truncated_attr, True)

    async def _start(self, command: list[str], working_directory: Path) -> _ProcessRecord | str:
        async with self._start_lock:
            for process_id in list(self.processes):
                existing = self.processes[process_id]
                if existing.process.returncode is not None and (
                    existing.readers is None or all(reader.done() for reader in existing.readers)
                ):
                    del self.processes[process_id]
            if len(self.processes) >= _MAX_PROCESSES:
                return "too many active processes; stop a process and retry"
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=working_directory,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=(os.name == "posix"),
                )
            except OSError as exc:
                return f"unable to start command: {exc}"

            process_id = str(uuid.uuid4())
            record = _ProcessRecord(process_id=process_id, process=process)
            assert process.stdout is not None
            assert process.stderr is not None
            record.readers = (
                asyncio.create_task(self._read_stream(process.stdout, record.stdout, record)),
                asyncio.create_task(self._read_stream(process.stderr, record.stderr, record)),
            )
            self.processes[process_id] = record
            return record

    async def _stop(self, record: _ProcessRecord) -> None:
        process = record.process
        if process.returncode is None:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
        readers = record.readers or ()
        waiters = asyncio.gather(process.wait(), *readers)
        try:
            await asyncio.wait_for(asyncio.shield(waiters), timeout=1.0)
        except TimeoutError:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                process.kill()
            await waiters

    def _output(self, record: _ProcessRecord, limit: int) -> dict[str, object]:
        stdout = record.stdout.decode("utf-8", errors="replace")
        stderr = record.stderr.decode("utf-8", errors="replace")
        truncated = record.stdout_truncated or record.stderr_truncated or len(stdout) > limit or len(stderr) > limit
        return {
            "process_id": record.process_id,
            "exit_code": record.process.returncode,
            "stdout": stdout[:limit],
            "stderr": stderr[:limit],
            "truncated": truncated,
        }

    async def execute(
        self, command: list[str], working_directory: str | None, timeout_seconds: float, max_output_chars: int
    ) -> dict[str, object]:
        error = self._validate_command(command)
        if error:
            return {"error": error}
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            return {"error": f"timeout_seconds must be greater than 0 and at most {_MAX_TIMEOUT_SECONDS:g}"}
        if not 1 <= max_output_chars <= _MAX_OUTPUT_LIMIT:
            return {"error": f"max_output_chars must be between 1 and {_MAX_OUTPUT_LIMIT}"}

        cwd = self._resolve_working_directory(working_directory)
        if isinstance(cwd, str):
            return {"error": cwd}
        record = await self._start(command, cwd)
        if isinstance(record, str):
            return {"error": record}
        timed_out = False
        readers = record.readers or ()
        waiters = asyncio.gather(record.process.wait(), *readers)
        try:
            await asyncio.wait_for(asyncio.shield(waiters), timeout=timeout_seconds)
        except TimeoutError:
            timed_out = True
            await self._stop(record)
            await waiters
        return {**self._output(record, max_output_chars), "timed_out": timed_out}

    async def start(
        self, command: list[str], working_directory: str | None, max_output_chars: int
    ) -> dict[str, object]:
        error = self._validate_command(command)
        if error:
            return {"error": error}
        if not 1 <= max_output_chars <= _MAX_OUTPUT_LIMIT:
            return {"error": f"max_output_chars must be between 1 and {_MAX_OUTPUT_LIMIT}"}

        cwd = self._resolve_working_directory(working_directory)
        if isinstance(cwd, str):
            return {"error": cwd}
        record = await self._start(command, cwd)
        if isinstance(record, str):
            return {"error": record}
        return {"process_id": record.process_id, "state": "running"}

    async def status(self, process_id: str, max_output_chars: int) -> dict[str, object]:
        if not 1 <= max_output_chars <= _MAX_OUTPUT_LIMIT:
            return {"error": f"max_output_chars must be between 1 and {_MAX_OUTPUT_LIMIT}"}
        record = self.processes.get(process_id)
        if record is None:
            return {"error": f"unknown process_id: {process_id}"}
        if record.process.returncode is not None and record.readers is not None:
            await asyncio.gather(*record.readers)
        return {
            **self._output(record, max_output_chars),
            "state": "running" if record.process.returncode is None else "exited",
        }

    async def stop(self, process_id: str, max_output_chars: int) -> dict[str, object]:
        if not 1 <= max_output_chars <= _MAX_OUTPUT_LIMIT:
            return {"error": f"max_output_chars must be between 1 and {_MAX_OUTPUT_LIMIT}"}
        record = self.processes.get(process_id)
        if record is None:
            return {"error": f"unknown process_id: {process_id}"}
        was_running = record.process.returncode is None
        await self._stop(record)
        return {**self._output(record, max_output_chars), "state": "stopped" if was_running else "exited"}


def register_execution(mcp: FastMCP) -> None:
    """Register terminal execution tools."""

    executor = TerminalExecutor.from_env()

    @mcp.tool(name="terminal_exec")
    async def terminal_exec(
        command: list[str],
        working_directory: str | None = None,
        timeout_seconds: float = 30.0,
        max_output_chars: int = _DEFAULT_OUTPUT_LIMIT,
    ) -> dict[str, object]:
        """Run one allowlisted command and return its bounded output and exit code."""

        return await executor.execute(command, working_directory, timeout_seconds, max_output_chars)

    @mcp.tool(name="terminal_start")
    async def terminal_start(
        command: list[str],
        working_directory: str | None = None,
        max_output_chars: int = _DEFAULT_OUTPUT_LIMIT,
    ) -> dict[str, object]:
        """Start an allowlisted command that may continue running."""

        return await executor.start(command, working_directory, max_output_chars)

    @mcp.tool(name="terminal_status")
    async def terminal_status(process_id: str, max_output_chars: int = _DEFAULT_OUTPUT_LIMIT) -> dict[str, object]:
        """Check a started process and retrieve its bounded output."""

        return await executor.status(process_id, max_output_chars)

    @mcp.tool(name="terminal_stop")
    async def terminal_stop(process_id: str, max_output_chars: int = _DEFAULT_OUTPUT_LIMIT) -> dict[str, object]:
        """Stop a started process and retrieve its final bounded output."""

        return await executor.stop(process_id, max_output_chars)
