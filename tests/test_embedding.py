from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vidgenie import embedding
from vidgenie.embedding import Embedder


class _FakeTextEmbedding:
    dim = 7

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [np.full(self.dim, i, dtype=np.float64) for i in range(len(texts))]


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> _FakeTextEmbedding:
    instance = _FakeTextEmbedding()

    def loader(**kw: Any) -> _FakeTextEmbedding:
        instance.kwargs = dict(kw)
        return instance

    monkeypatch.setattr(embedding, "_load_text_embedding", loader)
    return instance


def test_embed_shape_and_dtype(fake_model: _FakeTextEmbedding) -> None:
    emb = Embedder(model="fake-model")
    out = emb.embed(["satu kalimat", "dua kalimat"])
    assert out.shape == (2, 7)
    assert out.dtype == np.float32


def test_embed_empty(fake_model: _FakeTextEmbedding) -> None:
    emb = Embedder(model="fake-model")
    assert emb.embed([]).shape == (0, 0)


def test_embed_cache_dir_passed(fake_model: _FakeTextEmbedding) -> None:
    emb = Embedder(model="fake-model", cache_dir=Path("/tmp/cache"))
    emb.embed(["teks"])
    assert fake_model.kwargs == {"model_name": "fake-model", "cache_dir": "/tmp/cache"}
