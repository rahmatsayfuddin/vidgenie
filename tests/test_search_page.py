from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from vidgenie import embedding, main
from vidgenie.config import Settings
from vidgenie.storage import Storage


class _FakeModel:
    def __init__(self, vector: np.ndarray) -> None:
        self._vector = np.asarray(vector, dtype=np.float32)
        self.calls = 0

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls += 1
        return [self._vector for _ in texts]


def _seed(storage: Storage) -> dict[str, object]:
    ones = np.ones(7, dtype=np.float32)
    sparse = np.zeros(7, dtype=np.float32)
    sparse[0] = 1.0
    first = storage.save_media(b"img", "pantai.jpg", "image/jpeg")
    first.description = "pantai senja dengan ombak"
    first.description_status = "filled"
    first.embedding_status = "ready"
    storage.save_asset(first)
    storage.save_vector(first.id, ones)

    second = storage.save_media(b"img", "gunung.jpg", "image/jpeg")
    second.description = "pegunungan berkabut pagi hari"
    second.description_status = "filled"
    second.embedding_status = "ready"
    storage.save_asset(second)
    storage.save_vector(second.id, sparse)

    no_embed = storage.save_media(b"img", "kota.jpg", "image/jpeg")
    no_embed.description = "gedung kota di malam hari"
    no_embed.description_status = "filled"
    storage.save_asset(no_embed)

    no_desc = storage.save_media(b"img", "mobil.jpg", "image/jpeg")
    storage.save_asset(no_desc)
    return {"first": first, "second": second, "no_embed": no_embed, "no_desc": no_desc}


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Storage]:
    query_vec = np.ones(7, dtype=np.float32)
    model = _FakeModel(query_vec)
    monkeypatch.setattr(embedding, "_load_text_embedding", lambda **kw: model)
    monkeypatch.setattr(main, "_embedder", None)
    st = Storage(Settings(data_dir=tmp_path))
    monkeypatch.setattr(main, "storage", st)
    monkeypatch.setattr(main, "_worker", None)
    monkeypatch.setattr(main, "_worker_key", "")
    return TestClient(main.app), st


def test_search_page_returns_ranked_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, st = _client(tmp_path, monkeypatch)
    seed = _seed(st)
    resp = client.get("/search", params={"q": "pantai senja"})
    assert resp.status_code == 200
    text = resp.text
    assert "2 aset cocok" in text
    assert str(seed["first"].filename) in text
    assert str(seed["second"].filename) in text
    assert "Skor:" in text
    pos_pantai = text.index(str(seed["first"].filename))
    pos_gunung = text.index(str(seed["second"].filename))
    assert pos_pantai < pos_gunung
    assert str(seed["no_embed"].filename) not in text
    assert str(seed["no_desc"].filename) not in text


def test_search_page_scores_descending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, st = _client(tmp_path, monkeypatch)
    st.save_media(b"img", "a.jpg", "image/jpeg")
    _seed(st)
    resp = client.get("/search", params={"q": "sembarang"})
    assert "Skor: 1.00" in resp.text
    assert "Skor: 0.38" in resp.text


def test_search_page_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, st = _client(tmp_path, monkeypatch)
    _seed(st)
    resp = client.get("/search")
    assert resp.status_code == 200
    assert "Ketik query" in resp.text
    assert "tidak ada aset searchable yang cocok" not in resp.text.lower()


def test_search_page_no_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st = _client(tmp_path, monkeypatch)
    resp = client.get("/search", params={"q": "pesawat terbang di langit"})
    assert resp.status_code == 200
    assert "Tidak ada aset searchable yang cocok" in resp.text


def test_search_page_empty_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st = _client(tmp_path, monkeypatch)
    resp = client.get("/search", params={"q": "hutan lebat"})
    assert resp.status_code == 200
    assert "Tidak ada aset searchable yang cocok" in resp.text


def test_search_page_index_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _st = _client(tmp_path, monkeypatch)
    hp = client.get("/")
    assert hp.status_code == 200
    assert 'href="/search"' in hp.text
