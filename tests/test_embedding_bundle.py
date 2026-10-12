"""The desktop build ships embedding weights; they are copied into the data dir once."""
from pathlib import Path

from app.services.embedding import seed_cache_from_bundle


def _fake_bundle(root: Path) -> Path:
    bundle = root / "bundle"
    snap = bundle / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.onnx").write_bytes(b"weights")
    (bundle / ".locks").mkdir()
    (bundle / ".locks" / "x.lock").write_text("")
    return bundle


def test_bundle_is_copied_once_and_locks_are_left_behind(tmp_path):
    bundle = _fake_bundle(tmp_path)
    cache = tmp_path / "data" / "models"
    assert seed_cache_from_bundle(str(cache), str(bundle)) is True
    assert (cache / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc" / "model.onnx").read_bytes() == b"weights"
    assert not (cache / ".locks").exists()
    # Already seeded: nothing happens, even if the bundle changed.
    (bundle / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc" / "model.onnx").write_bytes(b"newer")
    assert seed_cache_from_bundle(str(cache), str(bundle)) is False
    assert (cache / "models--qdrant--all-MiniLM-L6-v2-onnx" / "snapshots" / "abc" / "model.onnx").read_bytes() == b"weights"


def test_no_bundle_or_no_cache_dir_is_a_no_op(tmp_path):
    assert seed_cache_from_bundle(str(tmp_path / "cache"), None) is False
    assert seed_cache_from_bundle(None, str(tmp_path)) is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert seed_cache_from_bundle(str(tmp_path / "cache"), str(empty)) is False
    assert not (tmp_path / "cache").exists()
