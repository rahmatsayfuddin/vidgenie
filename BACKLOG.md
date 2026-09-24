# BACKLOG.md

Backlog & progress tracker `vidgenie`.

- Khusus **task development** (arsitektur, feature, security, bug, setup, spike). Task dokumentasi/planning (edit `SDD.md`/`AGENTS.md` dll) **tidak** masuk di sini.
- Key ticket: prefix kategori (`ARCH`/`FEAT`/`SEC`/`BUG`/`SETUP`/`SPIKE`) + nomor urut.
- Aturan:
  - Mulai task → pindahkan tiket ke bagian `In Progress`.
  - Selesai → pindahkan ke `Done` + tulis **evidence** yang bisa diverifikasi (commit hash, path file, output lint/test/typecheck PASS, link artifact). Item `[x]` tanpa bukti = dianggap belum selesai.
- Batas MVP: semua tiket di `Backlog` (kecuali `BUG`, on-demand) tuntas.

## Backlog

### 🔷 Architecture
| Key | Judul | Prio |
|---|---|---|
| ARCH-003 | BackgroundWorker (in-process thread pool) + tabel `jobs`; `plan`/`embed`/`render` jalan async, UI polling (step job `planning`) | P1 |
| ARCH-004 | ~~Modul embedding lokal (CPU) + persist vektor `.npy` + registry id~~ → Done | P1 |
| ARCH-005 | ~~Modul search cosine (query teks → top-k aset, hanya aset `is_searchable` & embedding `ready`) + test relevansi; query embedding memakai `_query` scene~~ → Done | P1 |
| ARCH-006 | ~~Modul LLM client (OpenAI-compatible, env `VIDGENIE_LLM_*` + model + fallback kecil; retry eksponensial 429/5xx, timeout, `max_tokens`; parse JSON berlapis: strip fence → regex → fallback model kecil → heuristik pecah kalimat)~~ → Done | P1 |

### 🔧 Setup / Infrastructure
| Key | Judul | Prio |
|---|---|---|
| — | (kosong — SETUP-001/002/003 semua selesai) | — |

### ✨ Feature
| Key | Judul | Prio |
|---|---|---|
| FEAT-003 | Halaman `GET /assets/{id}` preview + metadata + editor deskripsi/tags manual | P1 |
| FEAT-004 | Status deskripsi + aturan "searchable": aset tanpa deskripsi tidak ikut pencarian | P1 |
| FEAT-005 | Re-embed massal | P2 |
| FEAT-006 | Plan: LLM pecah narasi → `scene[]{narration (potongan asli, bukan parafrase), search_query (cue visual), duration_sec clamp 2-12}`; few-shot; narasi overlay = `narration` | P1 |
| FEAT-007 | Search per scene + compose (top-k, anti-reuse, fallback caption-only) | P1 |
| FEAT-008 | Render ffmpeg 9:16 (scale/crop, zoompan foto, concat/xfade, drawtext narasi, amix musik) + `render.log` | P1 |
| FEAT-009 | Halaman build + preview scene + hasil/unduh MP4 + polling status job | P1 |

### 🛡️ Security
| Key | Judul | Prio |
|---|---|---|
| SEC-001 | Konfigurasi API key via env var (`VIDGENIE_LLM_*`); jangan commit secret | P1 |
| SEC-002 | Sanitasi upload: validasi tipe file, nama aman, batas ukuran, cegah path traversal | P1 |

### 🔬 Spike / Penelitian
| Key | Judul | Prio |
|---|---|---|
| — | (kosong — SPIKE-001 sudah selesai, lihat Done) | — |

### 🐞 Bug Fixing
| Key | Judul | Prio |
|---|---|---|
| — | (kosong; diisi on-demand saat ditemukan selama development) | — |

## In Progress
- (kosong)

## Done
- [x] **ARCH-006** — Modul LLM client (OpenAI-compatible)
  - Evidence:
    - Files: `src/vidgenie/llm.py` (`LLMConfig` + `from_settings`, `LLMClient.chat` dengan retry eksponensial 429/5xx + timeout + `max_tokens`, `LLMClient.complete_json` dengan fallback model kecil, `extract_json` berlapis (langsung → strip code fence → regex blok), `plan_scenes` + fallback heuristik pecah kalimat, `Scene`, `LLMError`), `src/vidgenie/config.py` (field `llm_base_url`/`llm_api_key`/`llm_model`/`llm_model_fallback`/`llm_timeout`/`llm_max_tokens`/`llm_max_retries` + helper `_env_float`/`_env_int` + `Settings.from_env` baca env `VIDGENIE_LLM_*`).
    - Tests: `tests/test_llm.py` (13 test; httpx `MockTransport`, tanpa jaringan) — retry 429 sukses, 4xx tanpa retry, give-up setelah `max_retries`, transport error, lapisan `extract_json`, fallback model, clamp durasi 2–12, heuristik, config env.
    - Verifikasi (`.venv` Python 3.14.2, ruff 0.16.8 / mypy 2.3.1 / pytest 9.1.1): `ruff check .` = All checks passed; `ruff format --check .` = 25 files already formatted; `mypy src` = Success, no issues found in 10 source files; `pytest -q` = **110 passed** (13 di antaranya `test_llm.py`).
    - Catatan: output `_query` (bukan `_query`) dipakai agar konsisten dengan kontrak ARCH-005/FEAT-006; config di-inject (`LLMConfig`) agar nanti bisa disuplai dari halaman Settings DB (task terpisah).
- [x] **SPIKE-001** — Validasi stack embedding lokal di aarch64 + Python 3.14
  - Médium: **`fastembed` + ONNX Runtime** (model `paraphrase-multilingual-MiniLM-L12-v2`, dim 384, ~0.22 GB).
  - Evidence:
    - `pip install fastembed` sukses di venv Python 3.14.6 (aarch64); dependensi inti: `onnxruntime-1.30.0-cp314-cp314-manylinux_2_28_aarch64.whl`, `numpy-2.5.3`, `tokenizers-0.23.2` (log install lengkap di sesi console).
    - Relevance test Indonesia PASS: query "pantai senja"→0.902 (dok pantai), "pegunungan berkabut"→0.811 (dok gunung), "kucing"→0.513 (dok kucing); throughput ≈30 doc/s CPU (100 doc = 3.4 s).
    - Wheel `torch-2.14.0-cp314-manylinux_2_28_aarch64` juga tersedia di PyPI → jalur fallback sentence-transformers terbuka (lebih berat).
    - Keputusan ditulis di `SDD.md` §7.2, §8, §9 (runtime/model/persist float32/cache_dir).
- [x] **SETUP-001** — Install dep inti di venv proyek (`.venv`)
  - Evidence: `fastapi-0.141.1`, `uvicorn-0.53.0`, `jinja2-3.1.6`, `python-multipart-0.0.32`, `httpx-0.28.1`, `pydantic-2.13.5`, `numpy-2.5.3`, `Pillow-12.3.0` — output `pip install` sukses di `.venv` (path: `/home/userland/dev/vidgenie/.venv`).
- [x] **SETUP-002** — Install & verifikasi ffmpeg
  - Evidence: `ffmpeg version 8.1.2-2+b3` (Debian), arsitektur aarch64; `--enable-libx264 --enable-libopus --enable-libvpx` dst terkonfigurasi — output `apt-get install -y ffmpeg` + `ffmpeg -version`.
- [x] **ARCH-001** — Scaffold package `src/vidgenie/` + `pyproject.toml` + dev tooling
  - Evidence:
    - Files: `pyproject.toml` (setuptools src-layout, deps, `[tool.ruff]`/`[tool.mypy]`/`[tool.pytest.ini_options]`), `src/vidgenie/__init__.py`, `src/vidgenie/sample.py`, `tests/test_sample.py`, `README.md`, `.gitignore`.
    - Verifikasi (`ruff` 0.16.7, `mypy` 2.3.1, `pytest` 9.1.1 di `.venv`): `ruff check .` = All checks passed; `ruff format .` = 2 reformatted; `mypy src` = Success, no issues (2 files); `pytest -q` = 1 passed.
- [x] **SETUP-003** — App minimal FastAPI + template
  - Evidence:
    - Files: `src/vidgenie/main.py` (FastAPI app, route `/` + `/health`), `templates/index.html`.
    - Uvicorn verifikasi: `uvicorn src.vidgenie.main:app --port 8721` → curl `GET /health` = `{"status":"ok"}` 200; `GET /` = HTML 200 (`<title>vidgenie</title>`); log: `200 OK` untuk kedua rute.
- [x] **ARCH-002** — Data model aset + layout folder + modul `storage`
  - Evidence:
    - Files: `src/vidgenie/config.py` (Settings dataclass + `ensure_dirs` + `from_env`), `src/vidgenie/models.py` (Asset dataclass + `to_dict`/`from_dict`), `src/vidgenie/storage.py` (Storage class + `save_media`/`load_asset`/`list_assets`/`detect_media_type`; ext image/video validation).
    - Tests (`tests/test_storage.py`, 6 test PASS, `ruff check` + `mypy` clean): `test_save_media_creates_file_and_sidecar`, `test_load_asset_roundtrip`, `test_list_assets_sorted`, `test_save_asset_updates_sidecar`, `test_detect_media_type`.
    - Layout konkret (`data/`): `assets/`, `sidecars/<id>.json`, `thumbs/`, `vectors/`, `vidgenie.db` — sesuai update `SDD.md` §4 & §5.
- [x] **FEAT-001** — `POST /upload` simpan file + thumbnail + probe metadata
  - Evidence:
    - Files: `src/vidgenie/media.py` (probe via Pillow/ffprobe untuk width/height/duration; `generate_thumbnail` gambar via Pillow 320x320, video via ffmpeg 320x320), `src/vidgenie/main.py` (`GET/POST /upload`), `templates/upload.html`.
    - Tests (13 pass; `ruff` + `mypy` clean): `tests/test_media.py` (probe & thumbnail gambar+video), `tests/test_upload.py` (upload 303→`/`, sidecar+thumb+metadata benar, ekstensi tak didukung → 400, form page).
    - Live verifikasi: upload JPG 640x480 via curl → `303`, data dir berisi `assets/<id>.jpg` + `sidecars/<id>.json` (width 640, height 480) + `thumbs/<id>.jpg`; upload `text/plain` → `HTTP 400`.
- [x] **FEAT-002** — Halaman `GET /assets` + filter + serving thumbnail
  - Evidence:
    - Files: `src/vidgenie/main.py` (`GET /assets` dengan filter `type`/`description_status`/`embedding_status`; `GET /media/thumbs/{filename}` dengan guard basename anti-traversal), `templates/assets.html` (grid kartu + form filter), `templates/index.html` (link ke daftar aset).
    - Tests (18 pass; `ruff`+`mypy` clean): `tests/test_assets.py` — list semua, filter type, filter status, empty state, serving thumbnail + penolakan traversal (HTTPException 400 / 404).
    - Live verifikasi: uvicorn → `GET /assets` 200; thumbnail aset 200.
- [x] **FEAT-003** — Halaman `GET /assets/{id}` + editor deskripsi/tags manual
  - Evidence:
    - Files: `src/vidgenie/main.py` (`GET /assets/{asset_id}` detail dengan regex `ASSET_ID_RE` guard 404; `POST /assets/{asset_id}` update deskripsi + tags dedupe, `description_status` filled/empty; `GET /media/assets/{filename}` serving media dengan basename guard; upload redirect sekarang → `/assets`), `templates/asset_detail.html` (preview video/img, tabel metadata, form edit), `templates/assets.html` (kartu jadi link ke detail).
    - Tests (22 pass; `ruff`+`mypy` clean): `tests/test_asset_detail.py` — metadata & form tampil, 404 untuk id invalid/tidak ada/traversal, edit set deskripsi+tags+status filled (dedupe tags, strip), clear deskripsi → status empty.
    - Live verifikasi (uvicorn + curl, data `/tmp/vg_ui`): upload JPG → 303 `/assets/<id>`; `POST` edit → 303, sidecar `description_status=filled`, `tags=["pantai","senja"]`, deskripsi tampil di halaman detail; clear → `empty`; id invalid → 404.
- [x] **FEAT-004** — Aturan searchable (aset tanpa deskripsi tidak ikut pencarian)
  - Evidence:
    - Files: `src/vidgenie/models.py` (`Asset.is_searchable` property = `description_status == "filled"`), `src/vidgenie/storage.py` (`list_searchable_assets()`), `templates/assets.html` (badge searchable/belum searchable di kartu).
    - Tests (24 pass; `ruff`+`mypy` clean): `tests/test_searchable.py` — property flip empty→filled, `list_searchable_assets` hanya memuat aset berdeskripsi.
- [x] **ARCH-004** — Modul embedding lokal (CPU) + persist vektor `.npy`
  - Evidence:
    - Dep: `pip install -e ".[embedding]"` sukses → `fastembed-0.8.0`, `onnxruntime-1.30.0`, `tokenizers-0.23.2` (log: `/tmp/pip_embed.log`, PIP_EXIT=0).
    - Files: `src/vidgenie/embedding.py` (class `Embedder`: lazy-load fastembed, `cache_dir` ke `data/models`, output `float32`; `_load_text_embedding` di-mock di test), `src/vidgenie/config.py` (`embedding_model` default `paraphrase-multilingual-MiniLM-L12-v2`, `embedding_dim=384`, `model_cache_dir`; env `VIDGENIE_EMBEDDING_MODEL`), `src/vidgenie/storage.py` (`vector_path`/`save_vector`/`load_vector`/`has_vector`).
    - Tests (29 pass; `ruff`+`mypy` clean): `tests/test_embedding.py` (shape/dtype float32, empty input, cache_dir diteruskan — fastembed di-mock), `tests/test_storage.py` (+2 test roundtrip vektor `.npy` float32 & missing).
    - Live integrasi (data `/tmp/vg_embed`): embed 3 dok → `(3, 384)` float32; query "pantai senja dengan ombak" → rank benar (pantai 20.7 > gunung 6.3 > kucing −0.8); model ter-download & ter-cache ke `models/`; persist+load `.npy` OK. Warning onnxruntime (pthread affinity/GPU discovery) harmless.
- [x] **ARCH-005** — Modul search cosine (query → top-k aset)
  - Evidence:
    - Files: `src/vidgenie/search.py` (`Searcher.search(query, top_k)` — kandidat = `is_searchable` & `embedding_status="ready"`; vektor dinormalisasi + cosine `matrix @ q`; skip aset tanpa vektor/norm-0; `SearchResult` dataclass), `src/vidgenie/storage.py` (`save_vector` sekarang flatten ke 1-D).
    - Tests (33 pass; `ruff`+`mypy` clean): `tests/test_search.py` — urutan cosine rank benar, `top_k`, eksklusi aset `pending`/deskripsi kosong/tanpa vektor, hasil kosong saat tanpa kandidat/vektor.
    - Live relevansi (data `/tmp/vg_search`, model real fastembed): dok korpus 4 aset → `pantai senja pasir putih`→`pantai.jpg` 0.769; `kucing di dalam rumah`→`kucing.jpg` 0.627; query tanpa aset (`pesawat terbang di langit`) → top-1 terlemah 0.361 (→ nanti fallback caption-only).

# Progress log

## Riwayat non-dev (dokumentasi/planning — tidak terhitung di backlog)
- 2026-09-14 — Analisis mesin & keputusan arsitektur (no GPU → CPU-only; RAG + ffmpeg). Evidence: output probe aarch64, Python 3.14.6, ffmpeg/node/uv absent; keputusan di `AGENTS.md` & `SDD.md`.
- 2026-09-14 — SDD v0.1 ditulis (`SDD.md`), termasuk pivot interface web (FastAPI + Jinja2).