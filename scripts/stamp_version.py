"""
Write one version number everywhere it is displayed.

    python scripts/stamp_version.py 0.2.0

Run by the release workflow with the version taken from the git tag, so the
installer, the desktop app and the API can never disagree about what they
are. Safe to run by hand before tagging.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def stamp_package(path: Path, version: str) -> None:
    # A textual edit rather than json.dump, so the file's own formatting
    # (compact arrays and all) survives and the diff is one line.
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^(\s*"version":\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1, flags=re.M
    )
    if count != 1:
        raise SystemExit(f"top-level version not found in {path}")
    json.loads(updated)  # still valid JSON
    path.write_text(updated, encoding="utf-8")


def stamp_config(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'APP_VERSION: str = "[^"]*"', f'APP_VERSION: str = "{version}"', text)
    if count != 1:
        raise SystemExit(f"APP_VERSION not found exactly once in {path}")
    path.write_text(updated, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2 or not SEMVER.match(sys.argv[1]):
        raise SystemExit("usage: stamp_version.py <major.minor.patch>")
    version = sys.argv[1]
    stamp_package(ROOT / "desktop" / "package.json", version)
    stamp_package(ROOT / "frontend" / "package.json", version)
    stamp_config(ROOT / "app" / "config.py", version)
    print(f"stamped {version}")


if __name__ == "__main__":
    main()
