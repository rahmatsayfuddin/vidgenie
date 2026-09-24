from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from vidgenie.config import Settings
from vidgenie.llm import LLMClient, LLMConfig, Scene


class PlanStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS plans ("
                "id TEXT PRIMARY KEY, "
                "narration TEXT NOT NULL, "
                "created_at TEXT NOT NULL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS scenes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "plan_id TEXT NOT NULL, "
                "idx INTEGER NOT NULL, "
                "narration_text TEXT NOT NULL, "
                "search_query TEXT NOT NULL, "
                "duration_sec REAL NOT NULL, "
                "asset_id TEXT, "
                "status TEXT NOT NULL DEFAULT 'pending')"
            )
            self._conn.commit()

    def save_scenes(self, plan_id: str, narration: str, scenes: list[Scene]) -> None:
        with self._lock:
            now = datetime.now(UTC).isoformat(timespec="seconds")
            self._conn.execute(
                "INSERT INTO plans (id, narration, created_at) VALUES (?, ?, ?)",
                (plan_id, narration, now),
            )
            self._conn.executemany(
                "INSERT INTO scenes "
                "(plan_id, idx, narration_text, search_query, duration_sec) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (plan_id, i, s.narration, s.search_query, s.duration_sec)
                    for i, s in enumerate(scenes)
                ],
            )
            self._conn.commit()

    def load_plan(self, plan_id: str) -> tuple[str, list[Scene]] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT narration FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if row is None:
                return None
            scene_rows = self._conn.execute(
                "SELECT narration_text, search_query, duration_sec "
                "FROM scenes WHERE plan_id = ? ORDER BY idx",
                (plan_id,),
            ).fetchall()
            scenes = [
                Scene(
                    narration=str(r[0]),
                    search_query=str(r[1]),
                    duration_sec=float(r[2]),
                )
                for r in scene_rows
            ]
            return str(row[0]), scenes

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def plan_scenes(narration: str, config: LLMConfig) -> list[Scene]:
    client = LLMClient(config)
    try:
        return client.plan_scenes(narration)
    finally:
        client.close()


def new_plan_id() -> str:
    return uuid.uuid4().hex
