import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vidgenie import embedding
from vidgenie.config import Settings
from vidgenie.storage import Storage
from vidgenie.worker import BackgroundWorker, JobStore


class _FakeModel:
    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.full(7, i, dtype=np.float64) for i in range(len(texts))]


def _worker_for(tmp_path: Path) -> BackgroundWorker:
    settings = Settings(data_dir=tmp_path)
    return BackgroundWorker(settings, Storage(settings))


def test_job_store_roundtrip(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    store = JobStore(settings)
    job_id = store.create("embed", {"asset_id": "abc"})
    job = store.get(job_id)
    assert job is not None
    assert job["kind"] == "embed"
    assert job["status"] == "queued"
    assert job["progress"] == 0
    assert job["payload"] == {"asset_id": "abc"}
    store.set_status(job_id, "running", step="mulai")
    store.set_progress(job_id, 40, step="embedding")
    store.finish(job_id)
    done = store.get(job_id)
    assert done is not None
    assert done["status"] == "done"
    assert done["progress"] == 100
    assert done["step"] == "embedding"
    store.close()

    reopened = JobStore(settings)
    assert reopened.get(job_id)["status"] == "done"
    assert reopened.get("00000000000000000000000000000000") is None
    reopened.close()


def test_job_store_fail(tmp_path: Path) -> None:
    store = JobStore(Settings(data_dir=tmp_path))
    job_id = store.create("embed", {})
    store.fail(job_id, "terjadi error")
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == "error"
    assert job["error"] == "terjadi error"
    store.close()


class _ReadySearchable:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        return np.stack([np.full(7, i, dtype=np.float64) for i in range(len(texts))]).astype(
            np.float32
        )


def _wait_job(worker_: BackgroundWorker, job_id: str, timeout: float = 5.0) -> dict:
    store = JobStore(worker_._settings)
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


def test_background_worker_embed_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _ReadySearchable()
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: fake)

    settings = Settings(data_dir=tmp_path)
    storage = Storage(settings)
    asset = storage.save_media(b"img", "pantai.jpg", "image/jpeg")
    asset.description = "pantai senja dengan ombak"
    asset.description_status = "filled"
    storage.save_asset(asset)

    w = _worker_for(tmp_path)
    job_id = w.submit("embed", {"asset_id": asset.id})
    job = _wait_job(w, job_id)
    assert job["status"] == "done"
    assert job["progress"] == 100

    updated = storage.load_asset(asset.id)
    assert updated is not None
    assert updated.embedding_status == "ready"
    assert storage.has_vector(asset.id)
    assert fake.calls == 1
    w.shutdown()


def test_background_worker_embed_not_searchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    settings = Settings(data_dir=tmp_path)
    storage = Storage(settings)
    asset = storage.save_media(b"img", "x.jpg", "image/jpeg")

    w = _worker_for(tmp_path)
    job_id = w.submit("embed", {"asset_id": asset.id})
    job = _wait_job(w, job_id)
    assert job["status"] == "error"
    assert "deskripsi" in job["error"]
    w.shutdown()


def test_background_worker_unknown_kind(tmp_path: Path) -> None:
    w = _worker_for(tmp_path)
    with pytest.raises(KeyError):
        w.submit("nuklir", {})
    w.shutdown()


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from vidgenie import main

    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    return TestClient(main.app)


def test_jobs_route_embed_and_poll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    client = _client(tmp_path, monkeypatch)
    st = main_storage(client)

    asset = st.save_media(b"img", "gunung.jpg", "image/jpeg")
    asset.description = "gunung berkabut di pagi hari"
    asset.description_status = "filled"
    st.save_asset(asset)
    resp = client.post(f"/assets/{asset.id}/embed")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert resp.json()["status"] == "queued"

    job = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        job = resp.json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert job is not None
    assert job["status"] == "done"

    assert client.get("/jobs/00000000000000000000000000000000").status_code == 404
    assert client.get("/jobs/invalid").status_code == 404


def test_embed_route_404_missing_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/assets/00000000000000000000000000000000/embed")
    assert resp.status_code == 404


def main_storage(client: TestClient) -> Storage:
    from vidgenie import main

    return main.storage
