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


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Storage]:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    monkeypatch.setattr(main, "_embedder", None)
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    return TestClient(main.app), st


def _fake_scenes(narration: str, config: object) -> list[Scene]:
    return [
        Scene(narration="Kalimat satu.", search_query="pantai", duration_sec=3.0),
        Scene(narration="Kalimat dua.", search_query="gunung", duration_sec=3.0),
    ]


def _seed_assets(st: Storage) -> dict[str, object]:
    a = st.save_media(b"img", "pantai.jpg", "image/jpeg")
    a.description = "pantai senja"
    a.description_status = "filled"
    a.embedding_status = "ready"
    st.save_asset(a)
    st.save_vector(a.id, np.ones(3, dtype=np.float32))

    b = st.save_media(b"img", "gunung.jpg", "image/jpeg")
    b.description = "gunung berkabut"
    b.description_status = "filled"
    b.embedding_status = "ready"
    st.save_asset(b)
    st.save_vector(b.id, np.zeros(3, dtype=np.float32))
    return {"a": a, "b": b}


def _make_plan(client: TestClient, st: Storage) -> str:
    st.save_media(b"img", "unused.jpg", "image/jpeg")

    resp = client.post(
        "/plan", data={"narration": "Dua kalimat. Dua lagi."}, follow_redirects=False
    )
    assert resp.status_code == 303
    return resp.headers["location"].rstrip("/").split("/")[-1]


def test_scene_search_returns_inline_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    assets = _seed_assets(st)
    plan_id = _make_plan(client, st)

    resp = client.post(f"/plan/{plan_id}/compose", follow_redirects=False)
    assert resp.status_code == 303

    resp = client.post(
        f"/plan/{plan_id}/search/0", data={"q": "pantai senja pasir putih"}, follow_redirects=False
    )
    assert resp.status_code == 200
    text = resp.text
    assert "Ganti aset" in text
    assert "pantai.jpg" in text
    assert "Gunakan aset" in text
    assert 'value="' + str(assets["a"].id) + '"' in text


def test_scene_search_does_not_mutate_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vidgenie.plan import PlanStore

    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    assets = _seed_assets(st)
    plan_id = _make_plan(client, st)
    client.post(f"/plan/{plan_id}/compose")
    store = PlanStore(st.settings)
    before = dict(store.load_composition(plan_id))
    store.close()

    client.post(f"/plan/{plan_id}/search/0", data={"q": "gunung"})
    store = PlanStore(st.settings)
    after = store.load_composition(plan_id)
    store.close()
    assert after == before
    assert assets["a"].id


def test_pick_asset_updates_composition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vidgenie.plan import PlanStore

    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    assets = _seed_assets(st)
    plan_id = _make_plan(client, st)
    client.post(f"/plan/{plan_id}/compose")

    # compose memilih aset a (score sama) → override scene 1 jadi aset b
    resp = client.post(
        f"/plan/{plan_id}/scenes/0/asset",
        data={"asset_id": str(assets["b"].id)},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/plan/{plan_id}"

    store = PlanStore(st.settings)
    composed = store.load_composition(plan_id)
    store.close()
    entry = composed[0]
    assert entry.asset_id == str(assets["b"].id)
    assert entry.status == "manual"

    page = client.get(f"/plan/{plan_id}")
    assert "gunung.jpg" in page.text


def test_pick_asset_upgrades_caption_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vidgenie.plan import PlanStore

    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    assets = _seed_assets(st)
    plan_id = _make_plan(client, st)
    client.post(f"/plan/{plan_id}/compose")

    client.post(
        f"/plan/{plan_id}/scenes/1/asset",
        data={"asset_id": str(assets["a"].id), "score": "0.500"},
    )
    store = PlanStore(st.settings)
    entry = store.load_composition(plan_id)[1]
    store.close()
    assert entry.asset_id == str(assets["a"].id)
    assert entry.status == "manual"
    assert entry.score is not None


def test_pick_asset_unknown_400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    _seed_assets(st)
    plan_id = _make_plan(client, st)
    client.post(f"/plan/{plan_id}/compose")

    assert (
        client.post(
            f"/plan/{plan_id}/scenes/0/asset", data={"asset_id": "00000000000000000000000000000000"}
        ).status_code
        == 400
    )


def test_pick_asset_requires_compose_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    assets = _seed_assets(st)
    plan_id = _make_plan(client, st)
    assert (
        client.post(
            f"/plan/{plan_id}/scenes/0/asset", data={"asset_id": str(assets["a"].id)}
        ).status_code
        == 400
    )


def test_scene_routes_unknown_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "plan_scenes", _fake_scenes)
    plan_id = _make_plan(client, _st)
    assert client.post(f"/plan/{plan_id}/search/9", data={"q": "x"}).status_code == 404
    assert client.post(f"/plan/{plan_id}/scenes/9/asset", data={"asset_id": "x"}).status_code == 404
    assert (
        client.post("/plan/00000000000000000000000000000000/search/0", data={"q": "x"}).status_code
        == 404
    )
