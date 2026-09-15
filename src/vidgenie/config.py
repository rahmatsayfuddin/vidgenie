from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    @property
    def sidecars_dir(self) -> Path:
        return self.data_dir / "sidecars"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def vectors_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def model_cache_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vidgenie.db"

    def ensure_dirs(self) -> None:
        for d in (self.assets_dir, self.sidecars_dir, self.thumbs_dir, self.vectors_dir):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("VIDGENIE_DATA_DIR", "data")),
            embedding_model=os.environ.get(
                "VIDGENIE_EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
        )
