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


def test_video_thumbnail(tmp_path: Path) -> None:
    src = tmp_path / "v.mp4"
    dest = tmp_path / "t.jpg"
    _make_mp4(src)
    media.generate_thumbnail(src, "video", dest)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size == (320, 320)
