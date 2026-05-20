"""Subprocess helpers shared across fusion packages."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_command(args: list[str], cwd: Path) -> CommandResult:
    """Run a command in the given working directory."""

    try:
        result = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False)
    except OSError as exc:
        return CommandResult(returncode=1, stdout="", stderr=str(exc))
    return CommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
