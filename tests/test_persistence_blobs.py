# tests/test_persistence_blobs.py
import pytest
from pathlib import Path
from core.persistence.blobs import BlobStore
from core.persistence.models import StorageCorrupt


def test_blob_store_put_and_get(tmp_path):
    store = BlobStore(tmp_path)
    data = b"Hello HERMES 2.x persistence world!"
    blob_id = store.put(data)

    assert len(blob_id) == 64  # SHA-256
    assert store.has(blob_id)
    assert store.get(blob_id) == data
    assert store.verify(blob_id) is True


def test_blob_store_deduplication(tmp_path):
    store = BlobStore(tmp_path)
    data = b"Shared content across multiple checkpoints"
    id1 = store.put(data)
    id2 = store.put(data)

    assert id1 == id2
    stats = store.get_stats()
    assert stats["total_blobs"] == 1
    assert stats["total_bytes"] == len(data)


def test_blob_store_detects_corruption(tmp_path):
    store = BlobStore(tmp_path)
    data = b"Pristine file content"
    blob_id = store.put(data)

    # Artificially corrupt the blob file on disk
    blob_path = store._blob_path(blob_id)
    with open(blob_path, "wb") as f:
        f.write(b"Tampered content")

    with pytest.raises(StorageCorrupt):
        store.get(blob_id)

    assert store.verify(blob_id) is False


def test_blob_store_put_file(tmp_path):
    store = BlobStore(tmp_path)
    sample_file = tmp_path / "sample.py"
    sample_file.write_text("print('test')", encoding="utf-8")

    blob_id = store.put_file(sample_file)
    assert store.has(blob_id)
    assert store.get(blob_id) == b"print('test')"
