from pathlib import Path

import numpy as np
import pytest

from vidgenie import embedding
from vidgenie.config import Settings
from vidgenie.embedding import Embedder
from vidgenie.search import Searcher
from vidgenie.storage import Storage


class _FakeModel:
    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.array([1.0, 0.0, 0.0], dtype=np.float64) for _ in texts]


@pytest.fixture
def searcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Searcher:
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: _FakeModel())
    storage = Storage(Settings(data_dir=tmp_path))
    return Searcher(storage, Embedder(model="fake"))


def _ready_asset(storage: Storage, filename: str) -> None:
    asset = storage.save_media(b"x", filename, "image/jpeg")
    asset.description = f"deskripsi {filename}"
    asset.description_status = "filled"
    asset.embedding_status = "ready"
    storage.save_asset(asset)
    storage.save_vector(asset.id, _vec_for(filename))


def _vec_for(filename: str) -> np.ndarray:
    vectors = {
        "a.jpg": [1.0, 0.0, 0.0],
        "b.jpg": [0.0, 1.0, 0.0],
        "c.jpg": [0.5, 0.5, 0.0],
    }
    return np.array(vectors.get(filename, [0.0, 0.0, 0.0]), dtype=np.float32)


def test_search_ranks_by_cosine(searcher: Searcher) -> None:
    st = searcher.storage
    _ready_asset(st, "a.jpg")
    _ready_asset(st, "b.jpg")
    _ready_asset(st, "c.jpg")
    results = searcher.search("query apa pun", top_k=3)
    assert [r.asset.filename for r in results] == ["a.jpg", "c.jpg", "b.jpg"]
    assert results[0].score > results[1].score > results[2].score


def test_search_top_k(searcher: Searcher) -> None:
    _ready_asset(searcher.storage, "a.jpg")
    _ready_asset(searcher.storage, "b.jpg")
    results = searcher.search("q", top_k=1)
    assert len(results) == 1
    assert results[0].asset.filename == "a.jpg"


def test_search_excludes_non_searchable_and_unready(searcher: Searcher) -> None:
    st = searcher.storage
    _ready_asset(st, "a.jpg")

    pending = st.save_media(b"x", "b.jpg", "image/jpeg")
    pending.description = "deskripsi"
    pending.description_status = "filled"
    pending.embedding_status = "pending"
    st.save_asset(pending)
    st.save_vector(pending.id, _vec_for("b.jpg"))

    empty = st.save_media(b"x", "c.jpg", "image/jpeg")
    empty.embedding_status = "ready"
    st.save_asset(empty)
    if not empty.is_searchable:
        st.save_vector(empty.id, _vec_for("c.jpg"))

    nov = st.save_media(b"x", "d.jpg", "image/jpeg")
    nov.description = "deskripsi"
    nov.description_status = "filled"
    nov.embedding_status = "ready"
    st.save_asset(nov)

    results = searcher.search("q", top_k=10)
    assert [r.asset.filename for r in results] == ["a.jpg"]


def test_search_with_no_candidates_or_no_vectors(searcher: Searcher) -> None:
    assert searcher.search("q") == []

    nov = searcher.storage.save_media(b"x", "d.jpg", "image/jpeg")
    nov.description = "deskripsi"
    nov.description_status = "filled"
    nov.embedding_status = "ready"
    searcher.storage.save_asset(nov)
    assert searcher.search("q") == []
