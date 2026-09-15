from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import numpy as np

from vidgenie.config import Settings
from vidgenie.models import Asset

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}


def detect_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    raise ValueError(f"unsupported media type: {ext or '(tanpa ekstensi)'}")


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()

    def save_media(self, data: bytes, filename: str, mime: str) -> Asset:
        media_type = detect_media_type(filename)
        ext = Path(filename).suffix.lower()
        asset_id = uuid.uuid4().hex
        rel_path = f"{asset_id}{ext}"
        self.settings.assets_dir.joinpath(rel_path).write_bytes(data)
        now = time.time()
        asset = Asset(
            id=asset_id,
            filename=filename,
            rel_path=rel_path,
            type=media_type,
            mime=mime or "application/octet-stream",
            mtime=now,
            size_bytes=len(data),
            description_status="empty",
            embedding_status="pending",
            created_at=now,
            updated_at=now,
        )
        self.save_asset(asset)
        return asset

    def sidecar_path(self, asset_id: str) -> Path:
        return self.settings.sidecars_dir / f"{asset_id}.json"

    def save_asset(self, asset: Asset) -> None:
        self.sidecar_path(asset.id).write_text(
            json.dumps(asset.to_dict(), indent=2), encoding="utf-8"
        )

    def load_asset(self, asset_id: str) -> Asset | None:
        path = self.sidecar_path(asset_id)
        if not path.exists():
            return None
        return Asset.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_assets(self) -> list[Asset]:
        result: list[Asset] = []
        for path in sorted(self.settings.sidecars_dir.glob("*.json")):
            result.append(Asset.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return result

    def list_searchable_assets(self) -> list[Asset]:
        return [a for a in self.list_assets() if a.is_searchable]

    def media_path(self, asset: Asset) -> Path:
        return self.settings.assets_dir / asset.rel_path

    def thumb_path(self, asset_id: str) -> Path:
        return self.settings.thumbs_dir / f"{asset_id}.jpg"

    def vector_path(self, asset_id: str) -> Path:
        return self.settings.vectors_dir / f"{asset_id}.npy"

    def save_vector(self, asset_id: str, vector: np.ndarray) -> Path:
        path = self.vector_path(asset_id)
        np.save(path, np.asarray(vector, dtype=np.float32).reshape(-1))
        return path

    def load_vector(self, asset_id: str) -> np.ndarray | None:
        path = self.vector_path(asset_id)
        if not path.exists():
            return None
        return np.load(path)

    def has_vector(self, asset_id: str) -> bool:
        return self.vector_path(asset_id).exists()
