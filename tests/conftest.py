import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for src in (
    ROOT / "packages" / "copilot-fusion" / "src",
    ROOT / "packages" / "contextwell-core" / "src",
    ROOT / "packages" / "contextwell-git" / "src",
    ROOT / "packages" / "contextwell-tools" / "src",
    ROOT / "packages" / "shared" / "src",
):
    sys.path.insert(0, str(src))
