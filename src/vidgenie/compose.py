from __future__ import annotations

from dataclasses import dataclass

from vidgenie.llm import Scene
from vidgenie.search import Searcher


@dataclass
class ComposedScene:
    idx: int
    narration_text: str
    search_query: str
    duration_sec: float
    caption: str
    asset_id: str | None
    score: float | None
    status: str


def compose_scenes(
    searcher: Searcher,
    scenes: list[Scene],
    *,
    top_k: int = 5,
    min_score: float = 0.35,
    reuse_gap: int = 2,
) -> list[ComposedScene]:
    used_at: dict[str, int] = {}
    composed: list[ComposedScene] = []

    def reusable(asset_id: str, idx: int) -> bool:
        last = used_at.get(asset_id, -reuse_gap - 1)
        return idx - last > reuse_gap

    for idx, scene in enumerate(scenes):
        results = searcher.search(scene.search_query, top_k=top_k)
        candidates = [r for r in results if r.score >= min_score]
        candidates.sort(key=lambda r: r.score, reverse=True)

        pick = next((r for r in candidates if reusable(r.asset.id, idx)), None)
        if pick is None and candidates:
            pick = candidates[0]

        if pick is not None:
            used_at[pick.asset.id] = idx
            composed.append(
                ComposedScene(
                    idx=idx,
                    narration_text=scene.narration,
                    search_query=scene.search_query,
                    duration_sec=scene.duration_sec,
                    caption=scene.narration,
                    asset_id=pick.asset.id,
                    score=pick.score,
                    status="matched",
                )
            )
        else:
            composed.append(
                ComposedScene(
                    idx=idx,
                    narration_text=scene.narration,
                    search_query=scene.search_query,
                    duration_sec=scene.duration_sec,
                    caption=scene.narration,
                    asset_id=None,
                    score=None,
                    status="caption_only",
                )
            )
    return composed
