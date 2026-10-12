"""Run the API against the local SQLite dev database (used by .claude/launch.json)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["MEET_COMPANION_CONFIG"] = "data/config.json"

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
