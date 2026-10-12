"""
Download the embedding model into a directory the desktop build ships.

The server normally fetches all-MiniLM-L6-v2 (~90 MB) on first use. A
desktop install on a machine without internet at first launch - or behind a
proxy that blocks Hugging Face - then has no search, Ask AI retrieval or
knowledge graph, and the failure is quiet. Bundling the weights removes
that dependency: the release workflow runs this before PyInstaller, and
desktop/server.spec ships the directory as `models/`, which the frozen
server copies into its data directory on first start.

The Hugging Face cache stores each snapshot file as a symlink into blobs/
wherever symlinks are allowed (the CI runners; not a Windows machine
without developer mode). PyInstaller copies those links as-is, and
electron-builder's 7-Zip then refuses the payload ("The directory name is
invalid"). So the cache is fetched into a scratch directory and rewritten
here as plain files, without blobs/ or lock files - the same layout, every
entry a real file.

    python scripts/fetch_embedding_model.py            # into desktop/models
    python scripts/fetch_embedding_model.py some/dir
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.services.embedding import _fastembed_name  # noqa: E402


def flatten(src: Path, dst: Path) -> int:
    """Copy the cache tree, resolving every link to its bytes; returns files written."""
    written = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        # Hub bookkeeping the model does not need: lock files, and the blob
        # store the snapshot links point into (its bytes land in the snapshot).
        dirs[:] = [d for d in dirs if d not in (".locks", "blobs") and not d.startswith(".")]
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.startswith("."):
                continue
            source = Path(root) / name
            target = dst / rel / name
            shutil.copyfile(source.resolve(), target)  # resolve(): follow the link, copy the bytes
            written += 1
    return written


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else PROJECT_ROOT / "desktop" / "models").resolve()
    from fastembed import TextEmbedding

    with tempfile.TemporaryDirectory(prefix="mc-embed-") as scratch:
        TextEmbedding(model_name=_fastembed_name(settings.EMBEDDING_MODEL), cache_dir=scratch, threads=1)
        if target.exists():
            shutil.rmtree(target)
        written = flatten(Path(scratch), target)

    # Reload from the flattened copy, offline: proves it is complete on its own.
    model = TextEmbedding(model_name=_fastembed_name(settings.EMBEDDING_MODEL), cache_dir=str(target), threads=1, local_files_only=True)
    vector = next(iter(model.embed(["ready"])))
    assert len(vector) == settings.EMBEDDING_DIMENSION, len(vector)
    links = [p for p in target.rglob("*") if p.is_symlink()]
    assert not links, f"links survived: {links[:3]}"
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print(f"embedding model {settings.EMBEDDING_MODEL} ready in {target}: {written} files, {size / 1_048_576:.0f} MB, no links")


if __name__ == "__main__":
    main()
