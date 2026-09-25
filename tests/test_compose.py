from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vidgenie import embedding, main
from vidgenie.compose import compose_scenes
from vidgenie.config import Settings
from vidgenie.embedding import Embedder
from vidgenie.llm import Scene
from vidgenie.plan import PlanStore, new_plan_id
from vidgenie.search import Searcher
from vidgenie.storage import Storage


class _FakeModel:
    def __init__(self, query_vec: np.ndarray) -> None:
        self.query_vec = np.asarray(query_vec, dtype=np.float64)

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self.query_vec for _ in texts]


def _vec(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    return TestClient(main.app)


def _searcher(storage: Storage, query_vec: np.ndarray) -> Searcher:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel(query_vec))
    return Searcher(storage, Embedder(model="fake"))


def _asset(storage: Storage, filename: str, vector: np.ndarray) -> None:
    asset = storage.save_media(b"x", filename, "image/jpeg")
    asset.description = f"deskripsi {filename}"
    asset.description_status = "filled"
    asset.embedding_status = "ready"
    storage.save_asset(asset)
    storage.save_vector(asset.id, vector)


def test_compose_picks_best_and_avoids_reuse(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    _asset(st, "pantai_a.jpg", _vec(1.0, 0.0))  # skor tinggi utk query vektor (1,0)
    _asset(st, "pantai_b.jpg", _vec(0.5, 0.5))  # skor menengah
    searcher = _searcher(st, _vec(1.0, 0.0))
    scenes = [
        Scene(narration="Scene 1.", search_query="pantai", duration_sec=4.0),
        Scene(narration="Scene 2.", search_query="pantai", duration_sec=4.0),
    ]
    composed = compose_scenes(searcher, scenes, min_score=0.0)
    assert [c.asset_id for c in composed] != [searcher.storage.list_assets()[0].id] * 2
    assert composed[0].status == "matched"
    assert composed[1].status == "matched"
    used = [c.asset_id for c in composed]
    assert used[0] != used[1]


def test_compose_reuse_when_pool_too_small(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    _asset(st, "satu.jpg", _vec(1.0, 0.0))
    searcher = _searcher(st, _vec(1.0, 0.0))
    scenes = [
        Scene(narration="Scene 1.", search_query="pantai", duration_sec=4.0),
        Scene(narration="Scene 2.", search_query="pantai", duration_sec=4.0),
    ]
    composed = compose_scenes(searcher, scenes, min_score=0.0)
    assert composed[0].status == "matched"
    assert composed[1].status == "matched"
    assert composed[1].asset_id == composed[0].asset_id


def test_compose_caption_only_when_no_candidate(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    _asset(st, "a.jpg", _vec(1.0, 0.0))
    searcher = _searcher(st, _vec(0.0, 1.0))  # ortogonal → skor 0
    scenes = [Scene(narration="Scene 1.", search_query="x", duration_sec=4.0)]
    composed = compose_scenes(searcher, scenes, min_score=0.9)
    assert composed[0].status == "caption_only"
    assert composed[0].asset_id is None


def test_compose_caption_only_when_no_assets(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    searcher = _searcher(st, _vec(1.0, 0.0))
    scenes = [Scene(narration="Scene 1.", search_query="x", duration_sec=4.0)]
    composed = compose_scenes(searcher, scenes)
    assert composed[0].status == "caption_only"


def _plan_with_scenes(tmp_path: Path) -> str:
    st = Storage(Settings(data_dir=tmp_path))
    _asset(st, "a.jpg", _vec(1.0, 0.0))
    store = PlanStore(st.settings)
    plan_id = new_plan_id()
    store.save_scenes(
        plan_id,
        "Narasi.",
        [Scene(narration="Scene 1.", search_query="pantai", duration_sec=4.0)],
    )
    store.close()
    return plan_id


def test_compose_roundtrip_via_plan_store(tmp_path: Path) -> None:
    plan_id = _plan_with_scenes(tmp_path)
    store = PlanStore(Settings(data_dir=tmp_path))
    data = store.load_plan(plan_id)
    assert data is not None
    st = Storage(Settings(data_dir=tmp_path))
    searcher = _searcher(st, _vec(1.0, 0.0))
    composed = compose_scenes(searcher, data[1], min_score=0.0)
    store.save_composition(plan_id, composed)
    loaded = store.load_composition(plan_id)
    assert loaded[0].asset_id is not None
    assert loaded[0].status == "matched"
    store.close()


def test_compose_route_303_and_shows_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = _plan_with_scenes(tmp_path)
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel(_vec(1.0, 0.0)))
    resp = client.post(f"/plan/{plan_id}/compose", follow_redirects=False)
    assert resp.status_code == 303
    detail = client.get(f"/plan/{plan_id}")
    assert detail.status_code == 200
    assert "a.jpg" in detail.text
    assert "matched" in detail.text


def test_compose_route_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/plan/tidak-ada/compose").status_code == 404
