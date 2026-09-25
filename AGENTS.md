# AGENTS.md

## Status
- Repo `vidgenie`: sudah ada scaffolding awal (`pyproject.toml`, `src/vidgenie/`, `tests/`) + dokumentasi (`AGENTS.md`, `BACKLOG.md`, `SDD.md`). **BACKLOG.md khusus task development — jangan diupdate untuk task dokumentasi/planning.**
- Arah produk: aplikasi **web** yang menyusun video dari library asset (gambar/video) berbasis **RAG atas deskripsi asset AI-friendly**; editing lokal via **ffmpeg**.
- Lingkungan (ARCH-008): **macOS Intel x86_64, tanpa GPU**; Python **3.12.6** (syarat agar `fastembed`/onnxruntime tersedia — onnxruntime tidak punya wheel utk cp314 mac-intel); `git`/`pip`/`venv`/`curl`/`uv` tersedia; `ffmpeg` 8.1_1 via Homebrew (binary `ffmpeg` jalan, `ffprobe` SIGABRT di mesin ini → jangan andalkan ffprobe dlm test). Dokumentasi desain: `SDD.md`.

## Keputusan arsitektur (lihat SDD.md)
- **Web app**: backend FastAPI + Uvicorn (localhost, single-user v1), frontend server-rendered Jinja2 + vanilla JS — **tanpa node/build step**.
- Pipeline: narasi teks bebas → LLM teks pecah scene → embedding lokal + cosine (SQLite metadata + `.npy` vektor) cari aset → ffmpeg render 9:16 (zoompan, concat, drawtext, amix musik).
- **Deskripsi aset**: ditulis **manual** oleh pengguna di UI (v1). LLM helper untuk draft deskripsi = v2 (tetap non-vision, jangan pakai vision LM).
- **Library only**: tanpa video generation (diffusers/torch dan tanpa API video-gen remote). Aset hanya dari DAM.
- Embedding **lokal CPU** (terverifikasi di mesin ini — SPIKE-001): **`fastembed` (ONNX Runtime)** + model `paraphrase-multilingual-MiniLM-L12-v2` (dim 384). Fallback sentence-transformers/torch bila perlu.
- Dep inti: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`, `pydantic`, `numpy`, `Pillow`; sistem: `ffmpeg`.
- LLM config via env: `VIDGENIE_LLM_BASE_URL`, `VIDGENIE_LLM_API_KEY`, dll. **Jangan pernah commit secret.**

## Perintah (terverifikasi di scaffolding — ARCH-001)
- Aktifkan venv dulu: `source .venv/bin/activate`
- Lint: `ruff check .`
- Format: `ruff format .`
- Typecheck: `mypy src`
- Test: `pytest`
- Satu test: `pytest tests/test_x.py::test_nama`
- Install package (editable + dev): `pip install -e ".[dev]"`
- Run app (belum ada; rencana): `uvicorn src.vidgenie.main:app --reload`

## Setup (sudah dieksekusi)
- `apt-get install ffmpeg` — tidak relevan di macOS; `ffmpeg` 8.1_1 via Homebrew (terpasang).
- Venv proyek: `.venv` (Python 3.12.6) — `source .venv/bin/activate` sebelum bekerja.
- Dep inti + dev + embedding (`fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`, `pydantic`, `numpy`, `Pillow`, `pytest`, `ruff`, `mypy`, `fastembed`+`onnxruntime`) terinstall via `pip install -e ".[dev,embedding]"`.
- App FastAPI berjalan (`uvicorn src.vidgenie.main:app --reload`), modul `storage.py`/`config.py`/`models.py` sudah ada.

## Konvensi
- Komentar kode minimal (tidak ada kecuali diminta).
- Dokumentasi & komunikasi dalam Bahasa Indonesia.
- Ikuti konvensi default Python/standard tooling sampai konvensi repo muncul.

## Workflow wajib
- Sebelum mengerjakan **task development**: pindahkan item ke bagian `In Progress` di `BACKLOG.md`; saat selesai pindah ke `Done` + tulis **evidence** yang bisa diverifikasi (commit hash, path file, output lint/test/typecheck PASS, link artifact). Item `[x]` tanpa bukti = dianggap belum selesai.
- Task dokumentasi/planning (edit `SDD.md`/`AGENTS.md` dll) **tidak** masuk `BACKLOG.md`.