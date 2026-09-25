from __future__ import annotations

import ipaddress
import json
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from vidgenie.config import Settings
from vidgenie.embedding import Embedder
from vidgenie.media import generate_thumbnail, probe
from vidgenie.models import Asset
from vidgenie.plan import PlanStore
from vidgenie.render import render_scenes
from vidgenie.storage import Storage

JOB_KINDS = ("embed", "plan", "render", "import", "import_batch")
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

_IMPORT_TIMEOUT = 60.0
_IMPORT_MAX_BYTES = 50 * 1024 * 1024
_IMPORT_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_IMPORT_PRIVATE_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
)

_IMPORT_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}


def validate_import_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL wajib http/https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL tidak punya host")
    if host in _IMPORT_BLOCKED_HOSTS:
        raise ValueError("host tidak diizinkan (suplai internal)")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise ValueError("alamat IP tidak diizinkan (private/loopback)")
    for net in _IMPORT_PRIVATE_NETS:
        if ip is not None and ip in net:
            raise ValueError("alamat IP tidak diizinkan (private)")


def download_image(url: str) -> tuple[bytes, str, str]:
    parsed = urlparse(url)
    base = Path(parsed.path).name or "gambar"
    data = bytearray()
    content_type = ""
    with httpx.stream(
        "GET",
        url,
        timeout=_IMPORT_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "vidgenie/1.0"},
    ) as resp:
        if resp.status_code != 200:
            raise ValueError(f"download gagal: HTTP {resp.status_code}")
        content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        total = int(resp.headers.get("content-length") or 0)
        if total > _IMPORT_MAX_BYTES:
            raise ValueError("ukuran file melebihi batas 50 MB")
        for chunk in resp.iter_bytes(chunk_size=64 * 1024):
            data.extend(chunk)
            if len(data) > _IMPORT_MAX_BYTES:
                raise ValueError("ukuran file melebihi batas 50 MB")
    ext = Path(base).suffix.lower()
    stem = Path(base).stem or "gambar"
    use_ct_ext = False
    if ext not in {*_IMPORT_MIME_EXT.values()} and content_type in _IMPORT_MIME_EXT:
        ext = _IMPORT_MIME_EXT[content_type]
        use_ct_ext = True
    if ext not in {*_IMPORT_MIME_EXT.values()}:
        raise ValueError(f"tautan tidak punya ekstensi gambar yang dikenali ({base})")
    if use_ct_ext or not Path(base).suffix.lower():
        filename = f"{stem}{ext}"
    else:
        filename = base
    if content_type not in _IMPORT_MIME_EXT and "image" not in content_type:
        raise ValueError(f"content-type bukan gambar: {content_type or 'kosong'}")
    return bytes(data), content_type, filename


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

    def update_payload(self, job_id: str, update: dict[str, Any]) -> None:
        existing = self.get(job_id)
        if existing is None:
            return
        payload = dict(existing.get("payload") or {})
        payload.update(update)
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET payload = ? WHERE id = ?",
                (json.dumps(payload), job_id),
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
            "render": self._render_task,
            "import": self._import_task,
            "import_batch": self._import_batch_task,
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
        store.set_progress(job_id, 20, step="embedding")
        self._embed_asset(asset)
        store.set_progress(job_id, 100, step="selesai")

    def _embed_asset(self, asset: Asset) -> None:
        if not asset.is_searchable:
            raise ValueError(f"aset {asset.id} belum punya deskripsi (tidak searchable)")
        text = asset.description
        if asset.tags:
            text = f"{text} {' '.join(asset.tags)}"
        embedder = Embedder(self._settings.embedding_model, self._settings.model_cache_dir)
        vectors = embedder.embed([text])
        if vectors.shape[0] == 0:
            raise ValueError("embedding menghasilkan vektor kosong")
        self._storage.save_vector(asset.id, vectors[0])
        asset.embedding_status = "ready"
        asset.embedding_id = asset.id
        self._storage.save_asset(asset)

    def _render_task(self, store: JobStore, job_id: str, payload: dict[str, Any]) -> None:
        plan_id = str(payload.get("plan_id") or "")
        if not plan_id:
            raise ValueError("plan_id wajib di payload render")
        store.set_progress(job_id, 10, step="memuat scene")
        plan_store = PlanStore(self._settings)
        data = plan_store.load_plan(plan_id)
        composed_by_idx = plan_store.load_composition(plan_id)
        if data is None:
            raise ValueError(f"plan tidak ditemukan: {plan_id}")
        if not composed_by_idx:
            raise ValueError("plan belum di-compose (jalankan compose dulu)")
        composed = [composed_by_idx[i] for i in sorted(composed_by_idx)]
        plan_store.close()

        dest = self._settings.outputs_dir / f"{plan_id}.mp4"
        dest.parent.mkdir(parents=True, exist_ok=True)
        music = self._select_music(payload)
        store.set_progress(job_id, 25, step="render tiap scene")
        result = render_scenes(self._storage, composed, dest, music_path=music)
        if not result.ok:
            raise ValueError(result.log or "render gagal")
        store.set_progress(job_id, 95, step="menyimpan hasil")
        if result.output is not None:
            store.finish(job_id, video_path=str(result.output), step="selesai")

    def _select_music(self, payload: dict[str, Any]) -> Path | None:
        name = str(payload.get("music") or "")
        if name:
            candidate = self._settings.music_dir / Path(name).name
            if candidate.exists():
                return candidate
        return self._first_music()

    def _first_music(self) -> Path | None:
        for ext in ("*.mp3", "*.m4a", "*.wav", "*.ogg"):
            for path in sorted(self._settings.music_dir.glob(ext)):
                return path
        return None

    def _import_task(self, store: JobStore, job_id: str, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "").strip()
        description = str(payload.get("description") or "").strip()
        if not url:
            raise ValueError("url wajib di payload import")
        if not description:
            raise ValueError("deskripsi wajib di payload import")
        validate_import_url(url)

        store.set_progress(job_id, 5, step="mengunduh gambar dari tautan")
        data, mime, filename = download_image(url)
        store.set_progress(job_id, 15, step="menyimpan aset")
        asset = self._import_save(data, filename, mime, description, payload.get("tags"))
        store.set_progress(job_id, 20, step="embedding")
        self._embed_asset(asset)
        store.update_payload(job_id, {"asset_id": asset.id})
        store.set_progress(job_id, 100, step="selesai")

    def _import_save(
        self,
        data: bytes,
        filename: str,
        mime: str,
        description: str,
        tags: object,
    ) -> Asset:
        try:
            asset = self._storage.save_media(data, filename, mime)
        except ValueError as exc:
            raise ValueError(f"tautan bukan media yang didukung ({filename}): {exc}") from exc
        asset.description = description
        if tags:
            asset.tags = [t.strip() for t in str(tags).split(",") if t.strip()]
        asset.description_status = "filled"
        asset.updated_at = time.time()
        self._storage.save_asset(asset)

        try:
            width, height, duration = probe(self._storage.media_path(asset), asset.type)
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise ValueError("tautan tidak berisi gambar yang valid") from exc
        asset.width, asset.height, asset.duration_sec = width, height, duration
        try:
            generate_thumbnail(
                self._storage.media_path(asset), asset.type, self._storage.thumb_path(asset.id)
            )
            asset.thumb = self._storage.thumb_path(asset.id).name
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
            pass
        self._storage.save_asset(asset)
        return asset

    def _import_batch_task(self, store: JobStore, job_id: str, payload: dict[str, Any]) -> None:
        lines = [str(r) for r in (payload.get("rows") or [])]
        if not lines:
            raise ValueError("tidak ada baris utk diimpor")
        total = len(lines)
        results: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            row_no = i + 1
            store.set_progress(job_id, int(i / total * 95), step=f"baris {row_no}/{total}")
            try:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError("JSON tidak valid") from exc
                if not isinstance(obj, dict):
                    raise ValueError("baris bukan objek JSON")
                url = str(obj.get("url") or "").strip()
                description = str(obj.get("description") or "").strip()
                if not url:
                    raise ValueError("kolom url kosong")
                if not description:
                    raise ValueError("kolom description kosong")
                validate_import_url(url)
                data, mime, filename = download_image(url)
                asset = self._import_save(data, filename, mime, description, obj.get("tags"))
                self._embed_asset(asset)
                results.append(
                    {
                        "row": row_no,
                        "ok": True,
                        "asset_id": asset.id,
                        "filename": asset.filename,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — toleransi error per baris
                results.append({"row": row_no, "ok": False, "error": str(exc)})
        ok_count = sum(1 for r in results if r["ok"])
        store.set_progress(job_id, 100, step="selesai")
        store.update_payload(
            job_id,
            {"results": results, "ok_count": ok_count, "error_count": total - ok_count},
        )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
