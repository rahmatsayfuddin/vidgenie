from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vidgenie import main
from vidgenie.config import Settings
from vidgenie.storage import Storage


def _make_two_assets(storage: Storage) -> None:
    storage.save_media(b"x", "a.jpg", "image/jpeg")
    video = storage.save_media(b"y", "b.mp4", "video/mp4")
    video.description = "klip senja"
    video.description_status = "filled"
    video.embedding_status = "ready"
    storage.save_asset(video)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    return TestClient(main.app)


def test_assets_page_lists_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    storage = main.storage
    _make_two_assets(storage)
    resp = client.get("/assets")
    assert resp.status_code == 200
    assert "a.jpg" in resp.text
    assert "b.mp4" in resp.text


def test_assets_page_filter_by_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _make_two_assets(main.storage)
    resp = client.get("/assets", params={"type": "image"})
    assert "a.jpg" in resp.text
    assert "b.mp4" not in resp.text


def test_assets_page_filter_by_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _make_two_assets(main.storage)
    resp = client.get("/assets", params={"description_status": "filled"})
    assert "b.mp4" in resp.text
    assert "a.jpg" not in resp.text


def test_assets_page_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/assets")
    assert resp.status_code == 200
    assert "Belum ada aset" in resp.text


def test_thumb_serving_and_safety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    storage = main.storage
    asset = storage.save_media(b"img", "foto.jpg", "image/jpeg")
    thumb_path = storage.thumb_path(asset.id)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(b"fake-thumb")
    resp = client.get(f"/media/thumbs/{asset.id}.jpg")
    assert resp.status_code == 200
    assert resp.content == b"fake-thumb"
    assert client.get("/media/thumbs/../../etc/passwd").status_code == 404
    assert client.get("/media/thumbs/tidak-ada.jpg").status_code == 404
    with pytest.raises(HTTPException) as excinfo:
        main.thumb("../../etc/passwd")
    assert excinfo.value.status_code == 400
