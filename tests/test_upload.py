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


class _FakeWorker:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict]] = []

    def submit(self, kind: str, payload: dict) -> str:
        self.jobs.append((kind, payload))
        return "0" * 32


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
    asset = st.list_assets()[0]
    assert resp.headers["location"] == f"/assets/{asset.id}"
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
    assert "Tambah dari tautan" in resp.text
    assert 'action="/assets/add-link"' in resp.text


def test_upload_with_description_auto_embed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    fw = _FakeWorker()
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_get_worker", lambda: fw)
    client = TestClient(main.app)

    resp = client.post(
        "/upload",
        files={"file": ("pantai.jpg", _jpg_bytes(), "image/jpeg")},
        data={"description": "pantai senja dengan ombak", "tags": "senja, laut"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    asset = st.list_assets()[0]
    assert resp.headers["location"] == f"/assets/{asset.id}"
    assert asset.description_status == "filled"
    assert asset.description == "pantai senja dengan ombak"
    assert asset.tags == ["senja", "laut"]
    assert fw.jobs == [("embed", {"asset_id": asset.id})]


def _gif_bytes(n_frames: int = 3) -> bytes:
    frames = [Image.new("RGB", (64, 48), (30 * i, 20 * i, 10)) for i in range(n_frames)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return buf.getvalue()


def test_upload_gif_treated_as_video(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    client = TestClient(main.app)

    resp = client.post(
        "/upload",
        files={"file": ("anim.gif", _gif_bytes(), "image/gif")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    asset = st.list_assets()[0]
    assert asset.type == "video"
    assert asset.mime == "image/gif"
    assert asset.width == 64
    assert asset.height == 48
    assert asset.duration_sec is not None and abs(asset.duration_sec - 0.3) < 0.05
    assert asset.thumb == f"{asset.id}.jpg"
    assert st.thumb_path(asset.id).exists()


def test_upload_without_description_no_embed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    fw = _FakeWorker()
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_get_worker", lambda: fw)
    client = TestClient(main.app)

    resp = client.post(
        "/upload",
        files={"file": ("pantai.jpg", _jpg_bytes(), "image/jpeg")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    asset = st.list_assets()[0]
    assert resp.headers["location"] == f"/assets/{asset.id}"
    assert asset.description_status == "empty"
    assert fw.jobs == []
