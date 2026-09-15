from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

THUMB_SIZE = (320, 320)


def probe(path: Path, asset_type: str) -> tuple[int | None, int | None, float | None]:
    if asset_type == "image":
        with Image.open(path) as img:
            return img.width, img.height, None
    return _probe_video(path)


def _probe_video(path: Path) -> tuple[int | None, int | None, float | None]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    width = int(stream["width"]) if stream and "width" in stream else None
    height = int(stream["height"]) if stream and "height" in stream else None
    duration_s = data.get("format", {}).get("duration")
    duration = float(duration_s) if duration_s else None
    return width, height, duration


def generate_thumbnail(path: Path, asset_type: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if asset_type == "image":
        with Image.open(path) as img:
            ImageOps.fit(img.convert("RGB"), THUMB_SIZE, method=Image.Resampling.LANCZOS).save(
                dest, "JPEG", quality=80
            )
        return
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "1",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:320:force_original_aspect_ratio=increase,crop=320:320",
            "-q:v",
            "4",
            str(dest),
        ],
        check=True,
    )
