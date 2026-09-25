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


def test_build_route_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/build").status_code == 404
    assert client.post("/build", data={"narration": "x"}).status_code == 404


def test_plan_detail_requires_compose_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/plan", data={"narration": "Halo."}, follow_redirects=False)
    assert resp.status_code == 303
    plan_id = resp.headers["location"].rstrip("/").split("/")[-1]

    page = client.get(f"/plan/{plan_id}")
    assert page.status_code == 200
    assert "Kalimat satu." in page.text
    assert "Render video" not in page.text
    assert "Jalankan" in page.text


def test_flow_to_job_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    client = _client(tmp_path, monkeypatch)

    resp = client.post("/plan", data={"narration": "Pagi itu cerah."}, follow_redirects=False)
    assert resp.status_code == 303
    plan_id = resp.headers["location"].rstrip("/").split("/")[-1]

    resp = client.post(f"/plan/{plan_id}/compose", follow_redirects=False)
    assert resp.status_code == 303

    page = client.get(f"/plan/{plan_id}")
    assert page.status_code == 200
    assert 'action="/plan/' + plan_id + '/render"' in page.text
    assert 'name="music"' in page.text

    resp = client.post(f"/plan/{plan_id}/render", data={"music": ""}, follow_redirects=False)
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


def test_render_without_compose_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/plan", data={"narration": "Halo."}, follow_redirects=False)
    plan_id = resp.headers["location"].rstrip("/").split("/")[-1]
    assert client.post(f"/plan/{plan_id}/render").status_code == 400


def test_render_unknown_plan_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/plan/00000000000000000000000000000000/render").status_code == 404


def test_job_result_404_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/jobs/00000000000000000000000000000000/result").status_code == 404
    assert client.get("/jobs/invalid/result").status_code == 404


def test_index_nav_points_to_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    hp = client.get("/")
    assert hp.status_code == 200
    assert 'href="/plan"' in hp.text
    assert 'href="/build"' not in hp.text
