from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vidgenie import main, plan
from vidgenie.config import Settings
from vidgenie.llm import Scene
from vidgenie.storage import Storage


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    return TestClient(main.app)


def _fake_scenes(narration: str, config: object) -> list[Scene]:
    return [Scene(narration="Scene A", search_query="gunung berkabut", duration_sec=4.0)]


def test_plan_store_roundtrip(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    store = plan.PlanStore(settings)
    plan_id = plan.new_plan_id()
    scenes = [
        Scene(narration="Kalimat satu.", search_query="pantai pagi", duration_sec=4.0),
        Scene(narration="Kalimat dua.", search_query="ombak", duration_sec=6.0),
    ]
    store.save_scenes(plan_id, "  Narasi utuh.  ", scenes)
    store.close()

    reopened = plan.PlanStore(settings)
    data = reopened.load_plan(plan_id)
    assert data is not None
    narration, loaded = data
    assert narration == "  Narasi utuh.  "
    assert [s.narration for s in loaded] == ["Kalimat satu.", "Kalimat dua."]
    assert [s.duration_sec for s in loaded] == [4.0, 6.0]
    assert reopened.load_plan("tidak-ada") is None
    reopened.close()


def test_plan_form_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/plan")
    assert resp.status_code == 200
    assert 'name="narration"' in resp.text


def test_plan_empty_narration_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/plan", data={"narration": "   "})
    assert resp.status_code == 400
    assert "wajib" in resp.text


def test_plan_run_persists_and_redirects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)

    resp = client.post("/plan", data={"narration": "Pagi itu cerah."}, follow_redirects=False)
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/plan/")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Pagi itu cerah." in detail.text
    assert "Scene A" in detail.text
    assert "gunung berkabut" in detail.text
    assert "4.0 s" in detail.text

    plan_id = location.removeprefix("/plan/")
    data = plan.PlanStore(main.storage.settings).load_plan(plan_id)
    assert data is not None
    assert len(data[1]) == 1


def test_plan_detail_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/plan/tidak-ada").status_code == 404
