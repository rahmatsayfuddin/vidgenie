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
from vidgenie.models import Asset
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
