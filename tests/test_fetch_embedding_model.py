"""
The bundled embedding model must be plain files: the Hugging Face cache uses
symlinks into blobs/ where it can, and 7-Zip (electron-builder) refuses to
pack those - the v0.6.0 Windows build failed on exactly this.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_embedding_model import flatten  # noqa: E402


def _fake_hub_cache(root: Path, *, with_links: bool) -> Path:
    cache = root / "cache"
    repo = cache / "models--qdrant--all-MiniLM-L6-v2-onnx"
    blobs = repo / "blobs"
    snap = repo / "snapshots" / "abc"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("abc")
    (repo / ".no_exist").mkdir()
    (cache / ".locks").mkdir()
    (cache / ".locks" / "x.lock").write_text("")
    for name, data in (("model.onnx", b"weights" * 100), ("config.json", b'{"a":1}')):
        blob = blobs / f"sha-{name}"
        blob.write_bytes(data)
        if with_links:
            os.symlink(blob, snap / name)
        else:
            (snap / name).write_bytes(data)
    return cache


def _symlinks_allowed(tmp_path: Path) -> bool:
    try:
        (tmp_path / "t").write_text("x")
        os.symlink(tmp_path / "t", tmp_path / "l")
        return True
    except (OSError, NotImplementedError):
        return False


def test_flatten_writes_plain_files_and_drops_hub_bookkeeping(tmp_path):
    links = _symlinks_allowed(tmp_path)
    cache = _fake_hub_cache(tmp_path, with_links=links)
    out = tmp_path / "out"
    written = flatten(cache, out)
    snap = out / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc"
    assert written == 3  # refs/main + two snapshot files
    assert (snap / "model.onnx").read_bytes() == b"weights" * 100
    assert (snap / "config.json").read_bytes() == b'{"a":1}'
    assert not any(p.is_symlink() for p in out.rglob("*"))
    assert not (out / "models--qdrant--all-MiniLM-L6-v2-onnx" / "blobs").exists()
    assert not (out / ".locks").exists()
    assert not (out / "models--qdrant--all-MiniLM-L6-v2-onnx" / ".no_exist").exists()
    if not links:
        pytest.skip("symlinks not permitted here; link resolution is exercised where they are (CI)")
