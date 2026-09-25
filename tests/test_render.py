from pathlib import Path

from PIL import Image

from vidgenie.compose import ComposedScene
from vidgenie.config import Settings
from vidgenie.render import _final_cmd, _segment_cmd, render_scenes
from vidgenie.storage import Storage


def _img(path: Path, size: tuple[int, int] = (400, 700)) -> Path:
    Image.new("RGB", size, (100, 140, 180)).save(path)
    return path


def _scene(idx: int, caption: str, dur: float, asset_id: str | None = "a1b2") -> ComposedScene:
    return ComposedScene(
        idx=idx,
        narration_text=caption,
        search_query="q",
        duration_sec=dur,
        caption=caption,
        asset_id=asset_id,
        score=0.9,
        status="matched",
    )


def _storage(tmp_path: Path) -> Storage:
    settings = Settings(data_dir=tmp_path / "data")
    storage = Storage(settings)
    return storage


def _tone(path: Path) -> Path:
    import subprocess

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "libmp3lame",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_segment_cmd_video_uses_trim(tmp_path: Path) -> None:
    pid = _scene(0, "caption", 4.0)
    cmd = _segment_cmd(pid, tmp_path / "v.mp4", "video", tmp_path / "c.txt", tmp_path / "s.mp4")
    joined = " ".join(cmd)
    assert "trim=duration=4" in joined
    assert "crop=720:1280" in joined
    assert "drawtext=textfile=" in joined


def _gif(path: Path, n_frames: int = 4) -> Path:
    frames = [Image.new("RGB", (160, 280), (40 * i, 30 * i, 20)) for i in range(n_frames)]
    frames[0].save(path, "GIF", save_all=True, append_images=frames[1:], duration=120, loop=0)
    return path


def test_segment_cmd_image_uses_zoompan(tmp_path: Path) -> None:
    img = _img(tmp_path / "i.jpg")
    pid = _scene(0, "caption", 4.0)
    cmd = _segment_cmd(pid, img, "image", tmp_path / "c.txt", tmp_path / "s.mp4")
    joined = " ".join(cmd)
    assert "zoompan" in joined
    assert "-loop 1" in joined
    assert "drawtext=textfile=" in joined


def test_segment_cmd_caption_only_placeholder(tmp_path: Path) -> None:
    pid = _scene(0, "caption", 4.0, asset_id=None)
    cmd = _segment_cmd(pid, None, None, tmp_path / "c.txt", tmp_path / "s.mp4")
    joined = " ".join(cmd)
    assert "placeholder.png" in joined


def test_segment_cmd_gif_loops_stream(tmp_path: Path) -> None:
    gif = _gif(tmp_path / "a.gif")
    pid = _scene(0, "caption", 4.0)
    cmd = _segment_cmd(pid, gif, "video", tmp_path / "c.txt", tmp_path / "s.mp4")
    joined = " ".join(cmd)
    assert "-stream_loop -1" in joined
    assert "-i " + str(gif) in joined
    assert "trim=duration=4" in joined
    assert "fps=30" in joined


def test_render_scenes_gif_end_to_end(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    gif = _gif(tmp_path / "a.gif")
    asset = storage.save_media(gif.read_bytes(), "a.gif", "image/gif")
    assert asset.type == "video"
    scenes = [_scene(0, "Animasi bergerak.", 2.0, asset.id)]
    dest = tmp_path / "out" / "v.mp4"
    result = render_scenes(storage, scenes, dest)
    assert result.ok, result.log
    assert result.output is not None
    assert result.output.exists() and result.output.stat().st_size > 0


def test_final_cmd_single_and_multi(tmp_path: Path) -> None:
    segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    cmd = _final_cmd(segs, [4.0, 5.0], tmp_path / "out.mp4", None, 0.3)
    joined = " ".join(cmd)
    assert "[0:v][1:v]xfade" in joined
    assert "offset=3.7" in joined
    assert "anullsrc" in joined
    assert "-shortest" in joined

    single = _final_cmd([segs[0]], [4.0], tmp_path / "out.mp4", None, 0.3)
    assert "xfade" not in " ".join(single)


def test_final_cmd_music_uses_volume_and_atrim(tmp_path: Path) -> None:
    cmd = _final_cmd([tmp_path / "a.mp4"], [4.0], tmp_path / "out.mp4", tmp_path / "m.mp3", 0.3)
    joined = " ".join(cmd)
    assert "volume=0.15" in joined
    assert "atrim=duration=4" in joined


def test_render_scenes_image_end_to_end(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    img = _img(tmp_path / "a.jpg")
    asset = storage.save_media(img.read_bytes(), "a.jpg", "image/jpeg")
    scenes = [_scene(0, "Selamat pagi dunia.", 1.5, asset.id)]
    dest = tmp_path / "out" / "v.mp4"
    result = render_scenes(storage, scenes, dest)
    assert result.ok, result.log
    assert result.output is not None
    assert result.output.exists() and result.output.stat().st_size > 0


def test_render_scenes_two_images_with_music(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    a = storage.save_media(_img(tmp_path / "a.jpg").read_bytes(), "a.jpg", "image/jpeg")
    b = storage.save_media(_img(tmp_path / "b.jpg").read_bytes(), "b.jpg", "image/jpeg")
    scenes = [_scene(0, "Scene satu.", 1.5, a.id), _scene(1, "Scene dua.", 1.5, b.id)]
    music = tmp_path / "m.mp3"
    _tone(music)
    dest = tmp_path / "out" / "v.mp4"
    result = render_scenes(storage, scenes, dest, music_path=music)
    assert result.ok, result.log
    assert result.output is not None
    assert result.output.stat().st_size > 0


def test_render_scenes_missing_asset_uses_placeholder(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    scenes = [_scene(0, "Tanpa aset.", 1.5, asset_id=None)]
    dest = tmp_path / "out" / "v.mp4"
    result = render_scenes(storage, scenes, dest)
    assert result.ok, result.log
    assert result.output is not None
    assert result.output.stat().st_size > 0
