from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_model_fallback: str = ""
    llm_timeout: float = 60.0
    llm_max_tokens: int = 1024
    llm_max_retries: int = 3

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
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def music_dir(self) -> Path:
        return self.data_dir / "assets" / "music"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vidgenie.db"

    def ensure_dirs(self) -> None:
        for d in (
            self.assets_dir,
            self.sidecars_dir,
            self.thumbs_dir,
            self.vectors_dir,
            self.outputs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            data_dir=Path(os.environ.get("VIDGENIE_DATA_DIR", "data")),
            embedding_model=os.environ.get(
                "VIDGENIE_EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            ),
            llm_base_url=os.environ.get("VIDGENIE_LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=os.environ.get("VIDGENIE_LLM_API_KEY", ""),
            llm_model=os.environ.get("VIDGENIE_LLM_MODEL", "gpt-4o-mini"),
            llm_model_fallback=os.environ.get("VIDGENIE_LLM_MODEL_FALLBACK", ""),
            llm_timeout=_env_float("VIDGENIE_LLM_TIMEOUT", 60.0),
            llm_max_tokens=_env_int("VIDGENIE_LLM_MAX_TOKENS", 1024),
            llm_max_retries=_env_int("VIDGENIE_LLM_MAX_RETRIES", 3),
        )
