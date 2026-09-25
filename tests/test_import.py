import io
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vidgenie import embedding, main
from vidgenie.config import Settings
from vidgenie.storage import Storage
from vidgenie.worker import (
    _IMPORT_MAX_BYTES,
    BackgroundWorker,
    JobStore,
    download_image,
    validate_import_url,
)


class _FakeModel:
    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([np.full(7, i, dtype=np.float32) for i in range(len(texts))])


def _jpg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 200, 30)).save(buf, "JPEG")
    return buf.getvalue()


def _wait_job(worker: BackgroundWorker, job_id: str, timeout: float = 5.0) -> dict:
    store = JobStore(worker._settings)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            job = store.get(job_id)
            if job is not None and job["status"] in ("done", "error"):
                return job
            time.sleep(0.05)
        raise AssertionError("job tidak selesai dalam batas waktu")
    finally:
        store.close()


class _FakeResp:
    def __init__(
        self,
        status_code: int,
        chunks: list[bytes] | None = None,
        content_type: str = "image/jpeg",
        content_length: int = 0,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks or [_jpg_bytes()]
        self.headers = {"content-type": content_type}
        if content_length:
            self.headers["content-length"] = str(content_length)

    def iter_bytes(self, *args: object, **kwargs: object) -> list[bytes]:
        return self._chunks


class _FakeStream:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    def __enter__(self) -> _FakeResp:
        return self._resp

    def __exit__(self, *args: object) -> None:
        return None


class _FakeHttpx:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    def stream(self, *args: object, **kwargs: object) -> _FakeStream:
        return _FakeStream(self._resp)


@pytest.fixture(autouse=True)
def _fake_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())


def test_validate_import_url_accepts_public_https() -> None:
    validate_import_url("https://example.com/cdn/foto.jpg")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x.jpg",
        "file:///etc/passwd",
        "https://",
        "http://localhost/x.jpg",
        "http://127.0.0.1/x.jpg",
        "http://10.0.0.5/x.jpg",
        "http://192.168.1.10/x.jpg",
        "http://172.16.9.1/x.jpg",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/x.jpg",
    ],
)
def test_validate_import_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        validate_import_url(url)


def test_download_image_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    import vidgenie.worker as worker

    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(_FakeResp(200)))
    data, mime, filename = download_image("https://example.com/pantai.jpg")
    assert data == _jpg_bytes()
    assert mime == "image/jpeg"
    assert filename == "pantai.jpg"


def test_download_image_ext_from_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    import vidgenie.worker as worker

    monkeypatch.setattr(
        worker.httpx,
        "stream",
        lambda *a, **k: _FakeStream(_FakeResp(200, content_type="image/png")),
    )
    _data, mime, filename = download_image("https://example.com/photo")
    assert mime == "image/png"
    assert filename.endswith(".png")
    assert filename.startswith("photo")


def test_download_image_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import vidgenie.worker as worker

    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(_FakeResp(404)))
    with pytest.raises(ValueError, match="404"):
        download_image("https://example.com/missing.jpg")


def test_download_image_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    import vidgenie.worker as worker

    resp = _FakeResp(200, [b"x" * (64 * 1024)], content_length=_IMPORT_MAX_BYTES + 1)
    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(resp))
    with pytest.raises(ValueError, match="50 MB"):
        download_image("https://example.com/big.jpg")


def test_download_image_non_image(monkeypatch: pytest.MonkeyPatch) -> None:
    import vidgenie.worker as worker

    resp = _FakeResp(200, [b"<html>"], content_type="text/html")
    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(resp))
    with pytest.raises(ValueError, match="content-type"):
        download_image("https://example.com/pantai.jpg")


def _worker_for(tmp_path: Path) -> BackgroundWorker:
    settings = Settings(data_dir=tmp_path)
    return BackgroundWorker(settings, Storage(settings))


def _fake_download(monkeypatch: pytest.MonkeyPatch, response: _FakeResp) -> None:
    import vidgenie.worker as worker

    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(response))


def test_import_task_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_download(monkeypatch, _FakeResp(200, [_jpg_bytes()]))
    st = Storage(Settings(data_dir=tmp_path))
    w = BackgroundWorker(st.settings, st)

    job_id = w.submit(
        "import",
        {
            "url": "https://example.com/hutan.jpg",
            "description": "hutan lebat dengan kabut pagi",
            "tags": "alam, hutan",
        },
    )
    job = _wait_job(w, job_id)
    assert job["status"] == "done"

    asset_id = str(job["payload"].get("asset_id") or "")
    assert asset_id
    asset = st.load_asset(asset_id)
    assert asset is not None
    assert asset.description == "hutan lebat dengan kabut pagi"
    assert asset.tags == ["alam", "hutan"]
    assert asset.description_status == "filled"
    assert asset.type == "image"
    assert asset.width == 64
    assert asset.height == 48
    assert asset.embedding_status == "ready"
    assert st.has_vector(asset_id)
    assert asset.thumb == f"{asset_id}.jpg"
    assert st.thumb_path(asset_id).exists()
    w.shutdown()


def test_import_task_missing_description(tmp_path: Path) -> None:
    w = _worker_for(tmp_path)
    job_id = w.submit("import", {"url": "https://example.com/x.jpg"})
    job = _wait_job(w, job_id)
    assert job["status"] == "error"
    assert "deskripsi" in job["error"]
    w.shutdown()


def test_import_task_download_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_download(monkeypatch, _FakeResp(500))
    w = _worker_for(tmp_path)
    job_id = w.submit("import", {"url": "https://example.com/x.jpg", "description": "x"})
    job = _wait_job(w, job_id)
    assert job["status"] == "error"
    assert "HTTP 500" in job["error"]
    w.shutdown()


def test_import_task_non_image_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_download(monkeypatch, _FakeResp(200, [b"<html>"]))
    w = _worker_for(tmp_path)
    job_id = w.submit("import", {"url": "https://example.com/x.jpg", "description": "x"})
    job = _wait_job(w, job_id)
    assert job["status"] == "error"
    assert "gambar yang valid" in job["error"]
    w.shutdown()


class _CaptureWorker:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict]] = []

    def submit(self, kind: str, payload: dict) -> str:
        self.jobs.append((kind, payload))
        return "1" * 32


def _client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Storage, _CaptureWorker]:
    st = Storage(Settings(data_dir=tmp_path))
    fw = _CaptureWorker()
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_get_worker", lambda: fw)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    return TestClient(main.app), st, fw


def test_add_link_route_submits_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st, fw = _client(tmp_path, monkeypatch)
    resp = client.post(
        "/assets/add-link",
        data={
            "url": "https://example.com/hutan.jpg",
            "description": "hutan lebat",
            "tags": "alam",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jobs/{'1' * 32}/result"
    assert fw.jobs == [
        (
            "import",
            {"url": "https://example.com/hutan.jpg", "description": "hutan lebat", "tags": "alam"},
        )
    ]


def test_add_link_route_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st, fw = _client(tmp_path, monkeypatch)
    assert client.post("/assets/add-link", data={"url": "", "description": "x"}).status_code == 400
    assert (
        client.post(
            "/assets/add-link", data={"url": "http://localhost/x.jpg", "description": "x"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/assets/add-link", data={"url": "https://example.com/x.jpg", "description": " "}
        ).status_code
        == 400
    )
    assert fw.jobs == []


def test_add_link_route_upload_page_has_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _st, _fw = _client(tmp_path, monkeypatch)
    resp = client.get("/upload")
    assert resp.status_code == 200
    assert 'name="url"' in resp.text
    assert 'name="description"' in resp.text
