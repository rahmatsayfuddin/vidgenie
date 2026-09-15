from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field, fields
from typing import Any


@dataclass
class Asset:
    id: str
    filename: str
    rel_path: str
    type: str
    mime: str
    mtime: float
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    thumb: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    description_status: str = "empty"
    embedding_id: str | None = None
    embedding_status: str = "pending"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_searchable(self) -> bool:
        return self.description_status == "filled"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Asset:
        init: dict[str, Any] = {}
        for f in fields(cls):
            if f.name in d:
                init[f.name] = d[f.name]
                continue
            if f.default is not MISSING:
                init[f.name] = f.default
            elif f.default_factory is not MISSING:
                init[f.name] = f.default_factory()
            else:
                raise ValueError(f"missing field: {f.name}")
        return cls(**init)
