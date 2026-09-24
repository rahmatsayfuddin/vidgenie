import json
import re
import subprocess
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from vidgenie import media
from vidgenie.config import Settings
from vidgenie.llm import LLMConfig
from vidgenie.models import Asset
from vidgenie.settings_store import LLM_KEYS, MASK, SettingsStore, resolve_llm_config
from vidgenie.storage import Storage

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
