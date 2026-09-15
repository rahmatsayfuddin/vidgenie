from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _load_text_embedding(**kwargs: Any) -> Any:  # pragma: no cover - di-mock di test
    from fastembed import TextEmbedding

    return TextEmbedding(**kwargs)


class Embedder:
    def __init__(self, model: str, cache_dir: Path | None = None) -> None:
        self.model = model
        self.cache_dir = cache_dir
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            kwargs: dict[str, Any] = {"model_name": self.model}
            if self.cache_dir is not None:
                kwargs["cache_dir"] = str(self.cache_dir)
            self._model = _load_text_embedding(**kwargs)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._get_model()
        vectors = [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]
        if not vectors:
            return np.zeros((0, 0), dtype=np.float32)
        return np.stack(vectors)
