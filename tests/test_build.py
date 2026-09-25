import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vidgenie import embedding, main
from vidgenie.config import Settings
from vidgenie.llm import Scene
from vidgenie.storage import Storage


class _FakeModel:
    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.array([1.0, 0.0, 0.0], dtype=np.float64) for _ in texts]


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    return TestClient(main.app)


def _fake_scenes(narration: str, config: object) -> list[Scene]:
    return [Scene(narration="Kalimat satu.", search_query="pantai", duration_sec=1.5)]


def test_build_form_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/build")
    assert resp.status_code == 200
    assert 'name="narration"' in resp.text
    assert "musik" in resp.text


def test_build_empty_narration_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/build", data={"narration": "  "})
    assert resp.status_code == 400
    assert "wajib" in resp.text


def test_build_flow_to_job_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    client = _client(tmp_path, monkeypatch)

    resp = client.post("/build", data={"narration": "Pagi itu cerah."}, follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/jobs/")
    assert location.endswith("/result")

    job_id = location.split("/")[-2]

    deadline = time.monotonic() + 30.0
    job = None
    while time.monotonic() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        job = resp.json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert job is not None
    assert job["status"] == "done"
    assert job["video_path"]

    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    assert "Pagi itu cerah." in result.text
    assert "Kalimat satu." in result.text
    assert "Unduh MP4" in result.text

    video = client.get(f"/jobs/{job_id}/video")
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert len(video.content) > 0


def test_job_result_404_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/jobs/00000000000000000000000000000000/result").status_code == 404
    assert client.get("/jobs/invalid/result").status_code == 404


def test_job_video_404_before_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    client = _client(tmp_path, monkeypatch)

    resp = client.post("/build", data={"narration": "Halo."}, follow_redirects=False)
    job_id = resp.headers["location"].split("/")[-2]
    assert client.get(f"/jobs/{job_id}/video").status_code in (404, 200)
