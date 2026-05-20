"""Path helpers shared across fusion packages."""

from pathlib import Path


def resolve_path(path: str) -> Path:
    """Resolve and expand a user-provided path."""

    return Path(path).expanduser().resolve()


def app_data_dir() -> Path:
    """Return the shared copilot-fusion data directory."""

    data_dir = Path.home() / ".copilot-fusion"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
