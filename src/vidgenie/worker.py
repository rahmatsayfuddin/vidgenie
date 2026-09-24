from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from vidgenie.config import Settings
from vidgenie.embedding import Embedder
from vidgenie.storage import Storage

JOB_KINDS = ("embed", "plan", "render")
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


class JobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(settings.db_path), check_same_thread=False, timeout=10.0)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "id TEXT PRIMARY KEY, "
                "kind TEXT NOT NULL, "
                "status TEXT NOT NULL, "
                "step TEXT, "
                "progress INTEGER NOT NULL DEFAULT 0, "
                "error TEXT, "
                "video_path TEXT, "
                "payload TEXT NOT NULL, "
                "created_at TEXT NOT NULL, "
                "finished_at TEXT)"
            )
            self._conn.commit()

    def create(self, kind: str, payload: dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, kind, status, step, progress, error, video_path, "
                "payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    kind,
                    STATUS_QUEUED,
                    None,
                    0,
                    None,
                    None,
                    json.dumps(payload),
                    now,
                ),
            )
            self._conn.commit()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, kind, status, step, progress, error, video_path, payload, "
                "created_at, finished_at FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "kind": str(row[1]),
            "status": str(row[2]),
            "step": row[3],
            "progress": int(row[4]) if row[4] is not None else 0,
            "error": row[5],
            "video_path": row[6],
            "payload": json.loads(str(row[7])) if row[7] else {},
            "created_at": str(row[8]),
            "finished_at": row[9],
        }

    def set_status(self, job_id: str, status: str, step: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, step = COALESCE(?, step) WHERE id = ?",
                (status, step, job_id),
            )
            self._conn.commit()

    def set_progress(self, job_id: str, progress: int, step: str | None = None) -> None:
        progress = max(0, min(100, int(progress)))
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET progress = ?, step = COALESCE(?, step) WHERE id = ?",
                (progress, step, job_id),
            )
            self._conn.commit()

    def finish(self, job_id: str, video_path: str | None = None, step: str | None = None) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, progress = 100, error = NULL, "
                "video_path = COALESCE(?, video_path), step = COALESCE(?, step), "
                "finished_at = ? WHERE id = ?",
                (STATUS_DONE, video_path, step, now, job_id),
            )
            self._conn.commit()

    def fail(self, job_id: str, error: str) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
                (STATUS_ERROR, error[:500], now, job_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class BackgroundWorker:
    def __init__(self, settings: Settings, storage: Storage, max_workers: int = 2) -> None:
        self._settings = settings
        self._storage = storage
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vg-job")
        self._tasks: dict[str, Callable[[JobStore, str, dict[str, Any]], None]] = {
            "embed": self._embed_task,
        }

    def submit(self, kind: str, payload: dict[str, Any]) -> str:
        if kind not in self._tasks:
            raise KeyError(f"job kind tidak dikenal: {kind}")
        store = JobStore(self._settings)
        job_id = store.create(kind, payload)
        store.close()
        self._pool.submit(self._run_job, job_id, kind, payload)
        return job_id

    def _run_job(self, job_id: str, kind: str, payload: dict[str, Any]) -> None:
        store = JobStore(self._settings)
        try:
            store.set_status(job_id, STATUS_RUNNING, step="mulai")
            self._tasks[kind](store, job_id, payload)
            store.finish(job_id)
        except Exception as exc:
            store.fail(job_id, str(exc))
        finally:
            store.close()

    def _embed_task(self, store: JobStore, job_id: str, payload: dict[str, Any]) -> None:
        asset_id = str(payload.get("asset_id") or "")
        if not asset_id:
            raise ValueError("asset_id wajib di payload embed")
        asset = self._storage.load_asset(asset_id)
        if asset is None:
            raise ValueError(f"aset tidak ditemukan: {asset_id}")
        if not asset.is_searchable:
            raise ValueError(f"aset {asset_id} belum punya deskripsi (tidak searchable)")
        text = asset.description
        if asset.tags:
            text = f"{text} {' '.join(asset.tags)}"
        store.set_progress(job_id, 20, step="embedding")
        embedder = Embedder(self._settings.embedding_model, self._settings.model_cache_dir)
        vectors = embedder.embed([text])
        if vectors.shape[0] == 0:
            raise ValueError("embedding menghasilkan vektor kosong")
        store.set_progress(job_id, 60, step="menyimpan vektor")
        self._storage.save_vector(asset.id, vectors[0])
        asset.embedding_status = "ready"
        asset.embedding_id = asset.id
        self._storage.save_asset(asset)
        store.set_progress(job_id, 100, step="selesai")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
