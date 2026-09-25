import subprocess
from pathlib import Path

from PIL import Image

from vidgenie import media


def _make_jpg(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    img = Image.new("RGB", size, (200, 80, 40))
    img.save(path, "JPEG")


def test_probe_image(tmp_path: Path) -> None:
    p = tmp_path / "a.jpg"
    _make_jpg(p, (64, 48))
    assert media.probe(p, "image") == (64, 48, None)


def test_image_thumbnail(tmp_path: Path) -> None:
    src = tmp_path / "a.jpg"
    dest = tmp_path / "t.jpg"
    _make_jpg(src, (640, 480))
    media.generate_thumbnail(src, "image", dest)
    with Image.open(dest) as img:
        assert img.size == (320, 320)


def _make_mp4(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=64x64:rate=10",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def test_probe_video(tmp_path: Path) -> None:
    p = tmp_path / "v.mp4"
    _make_mp4(p)
    width, height, duration = media.probe(p, "video")
    assert width == 64
    assert height == 64
    assert duration is not None and 1.5 < duration <= 3.0


def _make_gif(path: Path, n_frames: int = 3, size: tuple[int, int] = (64, 48)) -> None:
    frames = [Image.new("RGB", size, (30 * i, 20 * i, 10)) for i in range(n_frames)]
    frames[0].save(
        path,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )


def test_probe_gif_estimate_duration(tmp_path: Path) -> None:
    p = tmp_path / "a.gif"
    _make_gif(p, n_frames=3)
    width, height, duration = media.probe(p, "video")
    assert (width, height) == (64, 48)
    assert duration is not None and abs(duration - 0.3) < 0.05


def test_probe_single_frame_gif_no_duration(tmp_path: Path) -> None:
    p = tmp_path / "b.gif"
    _make_gif(p, n_frames=1)
    width, height, duration = media.probe(p, "video")
    assert (width, height) == (64, 48)
    assert duration is None


def test_gif_thumbnail_uses_first_frame(tmp_path: Path) -> None:
    src = tmp_path / "a.gif"
    dest = tmp_path / "t.jpg"
    _make_gif(src, n_frames=3)
    media.generate_thumbnail(src, "video", dest)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size == (320, 320)


def test_video_thumbnail(tmp_path: Path) -> None:
    src = tmp_path / "v.mp4"
    dest = tmp_path / "t.jpg"
    _make_mp4(src)
    media.generate_thumbnail(src, "video", dest)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size == (320, 320)
