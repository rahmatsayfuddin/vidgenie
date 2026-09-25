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
from vidgenie.worker import BackgroundWorker, JobStore


class _FakeModel:
    def embed(self, texts: list[str]) -> np.ndarray:
        return np.stack([np.full(7, i, dtype=np.float32) for i in range(len(texts))])


def _jpg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 200, 30)).save(buf, "JPEG")
    return buf.getvalue()


class _FakeResp:
    def __init__(
        self,
        status_code: int,
        chunks: list[bytes] | None = None,
        content_type: str = "image/jpeg",
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks or [_jpg_bytes()]
        self.headers = {"content-type": content_type}

    def iter_bytes(self, *args: object, **kwargs: object) -> list[bytes]:
        return self._chunks


class _FakeStream:
    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    def __enter__(self) -> _FakeResp:
        return self._resp

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())


def _fake_download(monkeypatch: pytest.MonkeyPatch, resp: _FakeResp) -> None:
    import vidgenie.worker as worker

    monkeypatch.setattr(worker.httpx, "stream", lambda *a, **k: _FakeStream(resp))


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


def test_import_batch_all_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_download(monkeypatch, _FakeResp(200))
    st = Storage(Settings(data_dir=tmp_path))
    w = BackgroundWorker(st.settings, st)

    lines = [
        '{"url": "https://example.com/a.jpg", "description": "pantai senja", "tags": "pantai"}',
        '{"url": "https://example.com/b.jpg", "description": "gunung berkabut"}',
    ]
    job = _wait_job(w, w.submit("import_batch", {"rows": lines}))
    assert job["status"] == "done"

    results = job["payload"]["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    for r in results:
        asset = st.load_asset(str(r["asset_id"]))
        assert asset is not None
        assert asset.description_status == "filled"
        assert asset.embedding_status == "ready"
        assert st.has_vector(asset.id)
    assert job["payload"]["ok_count"] == 2
    assert job["payload"]["error_count"] == 0
    w.shutdown()


def test_import_batch_per_row_error_tolerance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_download(monkeypatch, _FakeResp(200))
    lines = [
        '{"url": "https://example.com/ok.jpg", "description": "baik"}',
        "invalid json ini",
        '{"url": "https://example.com/bad.jpg"}',
        '{"url": "http://localhost/x.jpg", "description": "terblokir"}',
        '{"url": "https://example.com/gagal-download.jpg", "description": "x"}',
    ]
    st = Storage(Settings(data_dir=tmp_path))
    w = BackgroundWorker(st.settings, st)

    import vidgenie.worker as worker

    calls = {"n": 0}
    real_download = worker.download_image

    def side_effect(url: str) -> tuple[bytes, str, str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return real_download(url)
        if "gagal-download" in url:
            raise ValueError("download gagal: HTTP 500")
        return real_download(url)

    monkeypatch.setattr(worker, "download_image", side_effect)
    job = _wait_job(w, w.submit("import_batch", {"rows": lines}))
    assert job["status"] == "done"

    results = job["payload"]["results"]
    assert len(results) == 5
    assert [r["ok"] for r in results] == [True, False, False, False, False]
    assert "JSON tidak valid" in results[1]["error"]
    assert "description kosong" in results[2]["error"]
    assert "tidak diizinkan" in results[3]["error"]
    assert "HTTP 500" in results[4]["error"]
    assert job["payload"]["ok_count"] == 1
    assert job["payload"]["error_count"] == 4
    # hanya baris 1 yang menghasilkan aset
    assert sum(1 for a in st.list_assets() if a.filename in {"ok.jpg", "a.jpg"}) == 1
    w.shutdown()


def test_import_batch_no_rows_is_error(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    w = BackgroundWorker(st.settings, st)
    job = _wait_job(w, w.submit("import_batch", {"rows": []}))
    assert job["status"] == "error"
    assert "baris" in job["error"]
    w.shutdown()


class _CaptureWorker:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict]] = []

    def submit(self, kind: str, payload: dict) -> str:
        self.jobs.append((kind, payload))
        return "2" * 32


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _CaptureWorker]:
    st = Storage(Settings(data_dir=tmp_path))
    fw = _CaptureWorker()
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_get_worker", lambda: fw)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    return TestClient(main.app), fw


def test_import_batch_route_submits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, fw = _client(tmp_path, monkeypatch)
    jsonl = (
        '{"url": "https://example.com/a.jpg", "description": "pantai"}\n'
        '{"url": "https://example.com/b.jpg", "description": "gunung"}\n'
    )
    resp = client.post("/assets/import-batch", data={"jsonl": jsonl}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jobs/{'2' * 32}/result"
    assert fw.jobs == [
        (
            "import_batch",
            {
                "rows": [
                    '{"url": "https://example.com/a.jpg", "description": "pantai"}',
                    '{"url": "https://example.com/b.jpg", "description": "gunung"}',
                ]
            },
        )
    ]


def test_import_batch_route_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, fw = _client(tmp_path, monkeypatch)
    resp = client.post("/assets/import-batch", data={"jsonl": "  \n\t\n"})
    assert resp.status_code == 400
    assert "minimal satu baris" in resp.text

    lines = "\n".join(
        [f'{{"url": "https://example.com/{i}.jpg", "description": "x{i}"}}' for i in range(201)]
    )
    resp = client.post("/assets/import-batch", data={"jsonl": lines})
    assert resp.status_code == 400
    assert "200" in resp.text
    assert fw.jobs == []


def test_import_batch_route_upload_page_has_form(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _fw = _client(tmp_path, monkeypatch)
    resp = client.get("/upload")
    assert resp.status_code == 200
    assert 'name="jsonl"' in resp.text
    assert "/assets/import-batch" in resp.text


def test_job_result_shows_batch_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_download(monkeypatch, _FakeResp(200))
    st = Storage(Settings(data_dir=tmp_path))
    w = BackgroundWorker(st.settings, st)
    job = _wait_job(
        w,
        w.submit(
            "import_batch",
            {"rows": ['{"url": "https://example.com/a.jpg", "description": "x"}']},
        ),
    )
    w.shutdown()

    client, _fw = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "_get_worker", lambda: w)
    resp = client.get(f"/jobs/{job['id']}/result")
    assert resp.status_code == 200
    assert "Hasil impor massal" in resp.text
    assert "1 berhasil" in resp.text
    assert "berhasil" in resp.text
    assert "a.jpg" in resp.text
