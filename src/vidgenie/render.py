from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from vidgenie.compose import ComposedScene
from vidgenie.storage import Storage

WIDTH = 720
HEIGHT = 1280
FPS = 30
DEFAULT_CROSSFADE = 0.3
MUSIC_VOLUME = 0.15
DRAWTEXT_STYLE = (
    "fontsize=44:fontcolor=white:borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-text_h-80"
)
PLACEHOLDER_RGB = (32, 32, 38)


@dataclass
class RenderResult:
    ok: bool
    output: Path | None
    log: str


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _ensure_placeholder(path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (WIDTH, HEIGHT), PLACEHOLDER_RGB).save(path)
    return path


def _drawtext(cap_path: Path) -> str:
    return f"drawtext=textfile={cap_path}:{DRAWTEXT_STYLE}"


def _segment_cmd(
    composed: ComposedScene,
    asset_path: Path | None,
    asset_type: str | None,
    cap_path: Path,
    seg_path: Path,
) -> list[str]:
    asset_path = asset_path or _ensure_placeholder(seg_path.parent / "placeholder.png")
    if asset_type == "video":
        vf = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,"
            f"trim=duration={_fmt(composed.duration_sec)},setpts=PTS-STARTPTS,fps={FPS},"
            f"{_drawtext(cap_path)},format=yuv420p"
        )
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(asset_path),
            "-filter_complex",
            vf,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            str(seg_path),
        ]
    vf = (
        f"[0:v]scale=1440:2560:force_original_aspect_ratio=increase,"
        f"crop=1440:2560,setsar=1,"
        f"zoompan=z='min(zoom+0.0015,1.5)':d=1:s={WIDTH}x{HEIGHT}:fps={FPS},"
        f"{_drawtext(cap_path)},format=yuv420p"
    )
    return [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-t",
        _fmt(composed.duration_sec),
        "-i",
        str(asset_path),
        "-filter_complex",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        str(seg_path),
    ]


def _final_cmd(
    seg_paths: list[Path],
    durations: list[float],
    out_path: Path,
    music_path: Path | None,
    crossfade: float,
) -> list[str]:
    cmd = ["ffmpeg", "-y"]
    for seg in seg_paths:
        cmd += ["-i", str(seg)]
    if music_path is not None:
        cmd += ["-i", str(music_path)]
    music_index = len(seg_paths)

    filters: list[str] = []
    if len(seg_paths) == 1:
        filters.append("[0:v]copy[v]")
    else:
        label = "0:v"
        accumulated = 0.0
        for i in range(1, len(seg_paths)):
            offset = accumulated + durations[i - 1] - crossfade
            out_label = f"v{i}"
            filters.append(
                f"[{label}][{i}:v]xfade=transition=fade:duration={_fmt(crossfade)}:"
                f"offset={_fmt(offset)}[{out_label}]"
            )
            label = out_label
            accumulated = offset
        filters.append(f"[{label}]copy[v]")

    full = sum(durations) - crossfade * max(0, len(seg_paths) - 1)
    if music_path is not None:
        filters.append(
            f"[{music_index}:a]volume={_fmt(MUSIC_VOLUME)},"
            f"atrim=duration={_fmt(full)},asetpts=PTS-STARTPTS[a]"
        )
    else:
        filters.append(f"anullsrc=r=44100:cl=stereo,atrim=duration={_fmt(full)}[a]")

    cmd += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest", str(out_path)]
    return cmd


def render_scene(
    storage: Storage,
    composed: ComposedScene,
    seg_path: Path,
    cap_path: Path,
) -> tuple[int, str]:
    asset = storage.load_asset(composed.asset_id) if composed.asset_id else None
    asset_path = storage.media_path(asset) if asset else None
    asset_type = asset.type if asset else None
    cap_path.write_text(composed.caption, encoding="utf-8")
    result = subprocess.run(
        _segment_cmd(composed, asset_path, asset_type, cap_path, seg_path),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr


def render_scenes(
    storage: Storage,
    composed: list[ComposedScene],
    dest: Path,
    *,
    music_path: Path | None = None,
    crossfade: float = DEFAULT_CROSSFADE,
) -> RenderResult:
    workdir = dest.parent / f".{dest.stem}_seg"
    workdir.mkdir(parents=True, exist_ok=True)

    seg_paths: list[Path] = []
    durations: list[float] = []
    for i, scene in enumerate(composed):
        seg_path = workdir / f"seg_{i:03d}.mp4"
        cap_path = workdir / f"cap_{i:03d}.txt"
        code, stderr = render_scene(storage, scene, seg_path, cap_path)
        if code != 0:
            return RenderResult(ok=False, output=None, log=stderr)
        seg_paths.append(seg_path)
        durations.append(scene.duration_sec)

    if not seg_paths:
        return RenderResult(ok=False, output=None, log="tidak ada scene untuk dirender")

    final = _final_cmd(seg_paths, durations, dest, music_path, crossfade)
    result = subprocess.run(final, capture_output=True, text=True)
    if result.returncode != 0:
        log_path = Path(str(dest) + ".log")
        log_path.write_text(
            "ffmpeg command:\n" + " ".join(final) + "\n\nstderr:\n" + result.stderr,
            encoding="utf-8",
        )
        return RenderResult(ok=False, output=None, log=result.stderr)
    return RenderResult(ok=True, output=dest, log="")
