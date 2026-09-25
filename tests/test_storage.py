from pathlib import Path

import numpy as np
import pytest

from vidgenie.config import Settings
from vidgenie.storage import Storage, detect_media_type


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(Settings(data_dir=tmp_path))


def test_detect_media_type() -> None:
    assert detect_media_type("foto.JPG") == "image"
    assert detect_media_type("gambar.gif") == "video"
    assert detect_media_type("klip.mp4") == "video"
    with pytest.raises(ValueError):
        detect_media_type("data.txt")


def test_save_media_creates_file_and_sidecar(storage: Storage) -> None:
    asset = storage.save_media(b"fake-image-bytes", "pantai.jpg", "image/jpeg")
    assert asset.type == "image"
    assert asset.description_status == "empty"
    assert storage.media_path(asset).read_bytes() == b"fake-image-bytes"
    assert storage.sidecar_path(asset.id).exists()
    assert storage.thumb_path(asset.id).name == f"{asset.id}.jpg"


def test_load_asset_roundtrip(storage: Storage) -> None:
    asset = storage.save_media(b"x", "video.mp4", "video/mp4")
    loaded = storage.load_asset(asset.id)
    assert loaded is not None
    assert loaded == asset
    assert storage.load_asset("nonexistent") is None


def test_list_assets_sorted(storage: Storage) -> None:
    a1 = storage.save_media(b"1", "a.jpg", "image/jpeg")
    a2 = storage.save_media(b"2", "b.mp4", "video/mp4")
    ids = [a.id for a in storage.list_assets()]
    assert ids == sorted([a1.id, a2.id])


def test_save_asset_updates_sidecar(storage: Storage) -> None:
    asset = storage.save_media(b"x", "a.jpg", "image/jpeg")
    asset.description = "pantai senja"
    asset.description_status = "filled"
    storage.save_asset(asset)
    reloaded = storage.load_asset(asset.id)
    assert reloaded is not None
    assert reloaded.description == "pantai senja"
    assert reloaded.description_status == "filled"


def test_vector_save_load_roundtrip(storage: Storage) -> None:
    asset = storage.save_media(b"x", "a.jpg", "image/jpeg")
    vec = np.arange(384, dtype=np.float64)
    storage.save_vector(asset.id, vec)
    loaded = storage.load_vector(asset.id)
    assert loaded is not None
    assert loaded.shape == (384,)
    assert loaded.dtype == np.float32
    assert storage.has_vector(asset.id) is True


def test_vector_missing(storage: Storage) -> None:
    assert storage.has_vector("00000000000000000000000000000000") is False
    assert storage.load_vector("00000000000000000000000000000000") is None
