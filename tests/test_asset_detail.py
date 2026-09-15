from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vidgenie import main
from vidgenie.config import Settings
from vidgenie.storage import Storage


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    return TestClient(main.app)


def _save(cl: TestClient) -> str:
    return main.storage.save_media(b"img", "pantai.jpg", "image/jpeg").id


def test_asset_detail_shows_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    asset_id = _save(client)
    resp = client.get(f"/assets/{asset_id}")
    assert resp.status_code == 200
    assert "pantai.jpg" in resp.text
    assert "image/jpeg" in resp.text
    assert 'name="description"' in resp.text
    assert 'name="tags"' in resp.text


def test_asset_detail_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/assets/tidak-ada").status_code == 404
    assert client.get("/assets/00000000000000000000000000000000").status_code == 404
    assert client.get("/assets/../../etc/passwd").status_code == 404


def test_asset_edit_sets_description_and_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    asset_id = _save(client)
    resp = client.post(
        f"/assets/{asset_id}",
        data={"description": "  pantai senja dengan ombak  ", "tags": "pantai, senja, pantai"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/assets/{asset_id}"
    asset = main.storage.load_asset(asset_id)
    assert asset is not None
    assert asset.description == "pantai senja dengan ombak"
    assert asset.tags == ["pantai", "senja"]
    assert asset.description_status == "filled"


def test_asset_edit_clearing_description_sets_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    asset_id = _save(client)
    client.post(f"/assets/{asset_id}", data={"description": "ada deskripsi", "tags": "a"})
    client.post(f"/assets/{asset_id}", data={"description": "   ", "tags": ""})
    asset = main.storage.load_asset(asset_id)
    assert asset is not None
    assert asset.description == ""
    assert asset.tags == []
    assert asset.description_status == "empty"
