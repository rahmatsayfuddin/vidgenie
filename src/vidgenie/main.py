import json
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from vidgenie import media, plan
from vidgenie.compose import compose_scenes
from vidgenie.config import Settings
from vidgenie.embedding import Embedder
from vidgenie.llm import LLMConfig, LLMError
from vidgenie.models import Asset
from vidgenie.plan import PlanStore, plan_scenes
from vidgenie.search import Searcher
from vidgenie.settings_store import LLM_KEYS, MASK, SettingsStore, resolve_llm_config
from vidgenie.storage import Storage
from vidgenie.worker import BackgroundWorker, JobStore

REPO_ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(REPO_ROOT / "templates"))

app = FastAPI(title="vidgenie")
storage = Storage(Settings.from_env())


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="index.html", context={"title": "vidgenie"}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _settings_store() -> SettingsStore:
    return SettingsStore(storage.settings)


def _llm_config() -> LLMConfig:
    return resolve_llm_config(storage.settings, _settings_store())


_worker: BackgroundWorker | None = None
_worker_key = ""


def _get_worker() -> BackgroundWorker:
    global _worker, _worker_key
    key = str(storage.settings.db_path)
    if _worker is None or _worker_key != key:
        if _worker is not None:
            _worker.shutdown()
        _worker = BackgroundWorker(storage.settings, storage)
        _worker_key = key
    return _worker


def _settings_context(
    request: Request,
    values: dict[str, str],
    *,
    saved: bool = False,
    error: str = "",
) -> HTMLResponse:
    stored = _settings_store().all()
    api_key_set = bool(stored.get("api_key"))
    for key in ("base_url", "model", "model_fallback", "timeout", "max_tokens", "max_retries"):
        values[key] = values.get(key, "")
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        status_code=400,
        context={
            "title": "Pengaturan LLM",
            "values": values,
            "api_key_set": api_key_set,
            "api_key_mask": MASK if api_key_set else "",
            "saved": saved,
            "error": error,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    stored = _settings_store().all()
    values = {key: stored.get(key, "") for key in LLM_KEYS}
    values["api_key"] = ""
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "title": "Pengaturan LLM",
            "values": values,
            "api_key_set": bool(stored.get("api_key")),
            "api_key_mask": MASK if stored.get("api_key") else "",
            "saved": request.query_params.get("saved") == "1",
            "error": "",
        },
    )


@app.post("/settings", response_model=None)
def settings_save(
    request: Request,
    base_url: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    clear_api_key: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    model_fallback: Annotated[str, Form()] = "",
    timeout: Annotated[str, Form()] = "",
    max_tokens: Annotated[str, Form()] = "",
    max_retries: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    base_url = base_url.strip()
    model = model.strip()
    values = {
        "base_url": base_url,
        "api_key": "",
        "model": model,
        "model_fallback": model_fallback.strip(),
        "timeout": timeout.strip(),
        "max_tokens": max_tokens.strip(),
        "max_retries": max_retries.strip(),
    }

    error = ""
    if not base_url:
        error = "base_url wajib diisi."
    elif not model:
        error = "model wajib diisi."
    elif timeout.strip() and _is_not_float(timeout):
        error = "timeout harus angka."
    elif max_tokens.strip() and _is_not_int(max_tokens):
        error = "max_tokens harus bilangan bulat."
    elif max_retries.strip() and _is_not_int(max_retries):
        error = "max_retries harus bilangan bulat."
    if error:
        return _settings_context(request, values, error=error)

    to_set = {key: value for key, value in values.items() if value and key != "api_key"}
    to_delete = [key for key, value in values.items() if key != "api_key" and not value]
    if clear_api_key == "1":
        to_delete.append("api_key")
    elif api_key.strip():
        to_set["api_key"] = api_key.strip()

    store = _settings_store()
    store.set_many(to_set)
    for key in to_delete:
        store.delete(key)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


def _is_not_float(value: str) -> bool:
    try:
        float(value)
        return False
    except ValueError:
        return True


def _is_not_int(value: str) -> bool:
    try:
        int(value)
        return False
    except ValueError:
        return True


@app.get("/plan", response_class=HTMLResponse)
def plan_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="plan.html",
        context={"title": "Rancang scene", "narration": ""},
    )


@app.post("/plan", response_model=None)
def plan_run(
    request: Request,
    narration: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    narration = narration.strip()
    if not narration:
        return templates.TemplateResponse(
            request=request,
            name="plan.html",
            status_code=400,
            context={
                "title": "Rancang scene",
                "narration": narration,
                "error": "narasi wajib diisi.",
            },
        )
    try:
        scenes = plan_scenes(narration, _llm_config())
    except LLMError as exc:
        return templates.TemplateResponse(
            request=request,
            name="plan.html",
            status_code=400,
            context={"title": "Rancang scene", "narration": narration, "error": str(exc)},
        )
    if not scenes:
        return templates.TemplateResponse(
            request=request,
            name="plan.html",
            status_code=400,
            context={
                "title": "Rancang scene",
                "narration": narration,
                "error": "tidak ada scene yang dihasilkan.",
            },
        )
    plan_id = plan.new_plan_id()
    PlanStore(storage.settings).save_scenes(plan_id, narration, scenes)
    return RedirectResponse(url=f"/plan/{plan_id}", status_code=303)


@app.get("/plan/{plan_id}", response_class=HTMLResponse)
def plan_detail(request: Request, plan_id: str) -> HTMLResponse:
    store = PlanStore(storage.settings)
    data = store.load_plan(plan_id)
    if data is None:
        raise HTTPException(status_code=404)
    narration, scenes = data
    composed = store.load_composition(plan_id)
    rows: list[dict[str, object]] = []
    for idx, scene in enumerate(scenes):
        entry = composed.get(idx)
        rows.append(
            {
                "narration": scene.narration,
                "search_query": scene.search_query,
                "duration_sec": scene.duration_sec,
                "asset_id": entry.asset_id if entry else None,
                "score": entry.score if entry else None,
                "status": entry.status if entry else "pending",
                "asset": storage.load_asset(entry.asset_id) if entry and entry.asset_id else None,
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="plan_result.html",
        context={
            "title": "Hasil rancangan",
            "plan_id": plan_id,
            "narration": narration,
            "rows": rows,
        },
    )


@app.post("/plan/{plan_id}/compose")
def plan_compose(plan_id: str) -> RedirectResponse:
    store = PlanStore(storage.settings)
    data = store.load_plan(plan_id)
    if data is None:
        raise HTTPException(status_code=404)
    narration, scenes = data
    searcher = Searcher(
        storage, Embedder(storage.settings.embedding_model, storage.settings.model_cache_dir)
    )
    composed = compose_scenes(searcher, scenes)
    store.save_composition(plan_id, composed)
    return RedirectResponse(url=f"/plan/{plan_id}", status_code=303)


def _music_tracks() -> list[str]:
    music_dir = storage.settings.music_dir
    if not music_dir.exists():
        return []
    return sorted(p.name for p in music_dir.iterdir() if p.is_file())


@app.get("/build", response_class=HTMLResponse)
def build_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="build.html",
        context={"title": "Buat video", "narration": "", "music_tracks": _music_tracks()},
    )


@app.post("/build", response_model=None)
def build_run(
    request: Request,
    narration: Annotated[str, Form()] = "",
    music: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    narration = narration.strip()
    if not narration:
        return templates.TemplateResponse(
            request=request,
            name="build.html",
            status_code=400,
            context={
                "title": "Buat video",
                "narration": narration,
                "music_tracks": _music_tracks(),
                "error": "narasi wajib diisi.",
            },
        )
    try:
        scenes = plan_scenes(narration, _llm_config())
    except LLMError as exc:
        return templates.TemplateResponse(
            request=request,
            name="build.html",
            status_code=400,
            context={
                "title": "Buat video",
                "narration": narration,
                "music_tracks": _music_tracks(),
                "error": str(exc),
            },
        )
    if not scenes:
        return templates.TemplateResponse(
            request=request,
            name="build.html",
            status_code=400,
            context={
                "title": "Buat video",
                "narration": narration,
                "music_tracks": _music_tracks(),
                "error": "tidak ada scene yang dihasilkan.",
            },
        )
    plan_id = plan.new_plan_id()
    store = PlanStore(storage.settings)
    store.save_scenes(plan_id, narration, scenes)
    searcher = Searcher(
        storage, Embedder(storage.settings.embedding_model, storage.settings.model_cache_dir)
    )
    composed = compose_scenes(searcher, scenes)
    store.save_composition(plan_id, composed)
    job_id = _get_worker().submit("render", {"plan_id": plan_id, "music": music.strip() or ""})
    return RedirectResponse(url=f"/jobs/{job_id}/result", status_code=303)


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="upload.html", context={"title": "Upload aset"}
    )


@app.get("/assets", response_class=HTMLResponse)
def assets_page(
    request: Request,
    type: str | None = None,
    description_status: str | None = None,
    embedding_status: str | None = None,
) -> HTMLResponse:
    assets = storage.list_assets()
    if type in {"image", "video"}:
        assets = [a for a in assets if a.type == type]
    if description_status:
        assets = [a for a in assets if a.description_status == description_status]
    if embedding_status:
        assets = [a for a in assets if a.embedding_status == embedding_status]
    context = {
        "title": "Aset",
        "assets": assets,
        "type": type or "",
        "description_status": description_status or "",
        "embedding_status": embedding_status or "",
    }
    return templates.TemplateResponse(request=request, name="assets.html", context=context)


@app.get("/media/thumbs/{filename}")
def thumb(filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="nama file tidak valid")
    path = storage.settings.thumbs_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/media/assets/{filename}")
def media_file(filename: str) -> FileResponse:
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="nama file tidak valid")
    path = storage.settings.assets_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.post("/upload")
async def upload(file: Annotated[UploadFile, File()]) -> RedirectResponse:
    data = await file.read()
    filename = file.filename or "untitled"
    mime = file.content_type or ""
    try:
        asset = storage.save_media(data, filename, mime)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        width, height, duration = media.probe(storage.media_path(asset), asset.type)
        asset.width, asset.height, asset.duration_sec = width, height, duration
        media.generate_thumbnail(
            storage.media_path(asset), asset.type, storage.thumb_path(asset.id)
        )
        asset.thumb = storage.thumb_path(asset.id).name
        storage.save_asset(asset)
    except OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError:
        pass
    return RedirectResponse(url="/assets", status_code=303)


ASSET_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _load_asset_or_404(asset_id: str) -> Asset:
    if not ASSET_ID_RE.match(asset_id):
        raise HTTPException(status_code=404)
    asset = storage.load_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404)
    return asset


JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _job_or_404(job_id: str) -> dict[str, Any]:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=404)
    job = JobStore(storage.settings).get(job_id)
    if job is None:
        raise HTTPException(status_code=404)
    return job


@app.post("/assets/{asset_id}/embed")
def asset_embed(asset_id: str) -> JSONResponse:
    _load_asset_or_404(asset_id)
    job_id = _get_worker().submit("embed", {"asset_id": asset_id})
    return JSONResponse(content={"job_id": job_id, "status": "queued"}, status_code=202)


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    return JSONResponse(content=_job_or_404(job_id))


@app.get("/jobs/{job_id}/video")
def job_video(job_id: str) -> FileResponse:
    job = _job_or_404(job_id)
    video_path = job.get("video_path")
    if job.get("status") != "done" or not video_path:
        raise HTTPException(status_code=404)
    path = Path(str(video_path))
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="video/mp4")


@app.get("/jobs/{job_id}/result", response_class=HTMLResponse)
def job_result(request: Request, job_id: str) -> HTMLResponse:
    job = _job_or_404(job_id)
    plan_id = str(job.get("payload", {}).get("plan_id") or "")
    rows: list[dict[str, object]] = []
    narration = ""
    if plan_id:
        store = PlanStore(storage.settings)
        data = store.load_plan(plan_id)
        if data is not None:
            narration, scenes = data
            composed = store.load_composition(plan_id)
            for idx, scene in enumerate(scenes):
                entry = composed.get(idx)
                rows.append(
                    {
                        "idx": idx,
                        "narration": scene.narration,
                        "search_query": scene.search_query,
                        "duration_sec": scene.duration_sec,
                        "status": entry.status if entry else "pending",
                        "asset": (
                            storage.load_asset(entry.asset_id) if entry and entry.asset_id else None
                        ),
                    }
                )
    return templates.TemplateResponse(
        request=request,
        name="job_result.html",
        context={
            "title": "Hasil video",
            "job_id": job_id,
            "job": job,
            "plan_id": plan_id,
            "narration": narration,
            "rows": rows,
        },
    )


@app.get("/assets/{asset_id}", response_class=HTMLResponse)
def asset_detail(request: Request, asset_id: str) -> HTMLResponse:
    asset = _load_asset_or_404(asset_id)
    return templates.TemplateResponse(
        request=request,
        name="asset_detail.html",
        context={"title": asset.filename, "asset": asset},
    )


@app.post("/assets/{asset_id}")
def asset_edit(
    asset_id: str,
    description: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
) -> RedirectResponse:
    asset = _load_asset_or_404(asset_id)
    asset.description = description.strip()
    parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]
    unique_tags: list[str] = []
    for t in parsed_tags:
        if t not in unique_tags:
            unique_tags.append(t)
    asset.tags = unique_tags
    asset.description_status = "filled" if asset.description else "empty"
    storage.save_asset(asset)
    return RedirectResponse(url=f"/assets/{asset.id}", status_code=303)
