"""
Start the API and the web UI for development, in one terminal.

    python scripts/dev.py            # API on :8000, UI on :3000
    python scripts/dev.py --no-ui    # API only

Both processes are stopped together on Ctrl+C. Works the same on Windows,
macOS and Linux; needs the Python venv active (or run it with the venv's
python) and `npm --prefix frontend install` done once.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-ui", action="store_true", help="start only the API server")
    parser.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
    args = parser.parse_args()

    if sys.version_info[:2] != (3, 12):
        print(
            f"[dev] Warning: Python {sys.version_info.major}.{sys.version_info.minor} detected. "
            "This project targets Python 3.12; 3.13+ may fail to install some dependencies "
            "(pydantic-core). Create the venv with `py -3.12 -m venv .venv` if install failed.",
            file=sys.stderr,
        )
    os.chdir(ROOT)
    env = {**os.environ}
    env.setdefault("MEET_COMPANION_CONFIG", "data/config.json")

    procs: list[subprocess.Popen] = []
    api = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--reload"]
    procs.append(subprocess.Popen(api, env=env))
    print(f"[dev] API      http://127.0.0.1:{args.port}   (uvicorn --reload)")

    if not args.no_ui:
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            print("[dev] npm not found on PATH; starting the API only.", file=sys.stderr)
        elif not (ROOT / "frontend" / "node_modules").exists():
            print("[dev] frontend/node_modules missing - run `npm --prefix frontend install` first. Starting the API only.", file=sys.stderr)
        else:
            procs.append(subprocess.Popen([npm, "--prefix", "frontend", "run", "dev"], env=env))
            print("[dev] Web UI   http://localhost:3000   (vite, proxies /api to the API)")

    print("[dev] Ctrl+C stops everything.")

    def stop(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # If either process dies on its own, bring the other down too so a
    # crashed API doesn't leave a UI that can only show errors.
    while True:
        for p in procs:
            if p.poll() is not None:
                print(f"[dev] a process exited with code {p.returncode}; stopping the rest.", file=sys.stderr)
                stop()
        try:
            procs[0].wait(timeout=1)
        except subprocess.TimeoutExpired:
            continue


if __name__ == "__main__":
    raise SystemExit(main())
