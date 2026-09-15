from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vidgenie.embedding import Embedder
from vidgenie.models import Asset
from vidgenie.storage import Storage


@dataclass
class SearchResult:
    score: float
    asset: Asset


class Searcher:
    def __init__(self, storage: Storage, embedder: Embedder) -> None:
        self.storage = storage
        self.embedder = embedder

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        candidates = [
            a
            for a in self.storage.list_assets()
            if a.is_searchable and a.embedding_status == "ready"
        ]
        if not candidates:
            return []
        query_vec = self.embedder.embed([query])
        if query_vec.shape[0] == 0:
            return []
        q = query_vec[0]
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm

        rows: list[np.ndarray] = []
        assets: list[Asset] = []
        for asset in candidates:
            vector = self.storage.load_vector(asset.id)
            if vector is None:
                continue
            vector = np.asarray(vector).reshape(-1)
            norm = np.linalg.norm(vector)
            if norm == 0:
                continue
            rows.append(vector / norm)
            assets.append(asset)
        if not rows:
            return []

        scores = np.stack(rows) @ q
        order = np.argsort(-scores)[:top_k]
        return [SearchResult(score=float(scores[i]), asset=assets[int(i)]) for i in order]
