import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vidgenie import main
from vidgenie.config import Settings
from vidgenie.storage import Storage


def _jpg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 200, 30)).save(buf, "JPEG")
    return buf.getvalue()


def test_upload_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    client = TestClient(main.app)

    resp = client.post(
        "/upload",
        files={"file": ("pantai.jpg", _jpg_bytes(), "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/assets"

    assets = st.list_assets()
    assert len(assets) == 1
    asset = assets[0]
    assert asset.type == "image"
    assert asset.width == 64
    assert asset.height == 48
    assert asset.thumb == f"{asset.id}.jpg"
    assert st.media_path(asset).exists()
    assert st.thumb_path(asset.id).exists()


def test_upload_rejects_unsupported_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    client = TestClient(main.app)

    resp = client.post("/upload", files={"file": ("data.txt", b"hello", "text/plain")})
    assert resp.status_code == 400
    assert st.list_assets() == []


def test_upload_form_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    client = TestClient(main.app)
    resp = client.get("/upload")
    assert resp.status_code == 200
    assert 'action="/upload"' in resp.text
