from __future__ import annotations

import sqlite3
import threading

from vidgenie.config import Settings
from vidgenie.llm import LLMConfig

LLM_KEYS = (
    "base_url",
    "api_key",
    "model",
    "model_fallback",
    "timeout",
    "max_tokens",
    "max_retries",
)
MASK = "********"


def mask_api_key(value: str | None) -> str:
    if not value:
        return ""
    return MASK


def resolve_llm_config(settings: Settings, store: SettingsStore | None) -> LLMConfig:
    base = LLMConfig.from_settings(settings)
    if store is None:
        return base
    stored = store.all()
    if not stored:
        return base
    timeout = base.timeout
    if stored.get("timeout"):
        try:
            timeout = float(stored["timeout"])
        except ValueError:
            pass
    max_tokens = base.max_tokens
    if stored.get("max_tokens"):
        try:
            max_tokens = int(stored["max_tokens"])
        except ValueError:
            pass
    max_retries = base.max_retries
    if stored.get("max_retries"):
        try:
            max_retries = int(stored["max_retries"])
        except ValueError:
            pass
    return LLMConfig(
        base_url=stored.get("base_url") or base.base_url,
        api_key=stored.get("api_key") or base.api_key,
        model=stored.get("model") or base.model,
        model_fallback=stored.get("model_fallback") or base.model_fallback,
        timeout=timeout,
        max_tokens=max_tokens,
        max_retries=max_retries,
    )


class SettingsStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.commit()

    def all(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
            return {row[0]: row[1] for row in rows}

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return str(row[0]) if row else None

    def set(self, key: str, value: str) -> None:
        self.set_many({key: value})

    def set_many(self, values: dict[str, str]) -> None:
        if not values:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                list(values.items()),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
