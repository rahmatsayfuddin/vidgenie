# SDD — vidgenie

Software Design Document v0.1 (draft). Dokumen ini menjelaskan desain aplikasi `vidgenie`: sistem web untuk menyusun video dari library asset (gambar/video) berbasis RAG, dengan editing lokal via ffmpeg.

## 1. Ringkasan eksekutif

- `vidgenie` adalah aplikasi web **single-user, localhost** yang menerima narasi teks bebas, memecahnya menjadi scene, mencari asset paling cocok dari **Digital Asset Management (DAM) milik sendiri**, lalu merender video vertikal (9:16) menggabungkan asset + teks overlay (narasi per scene) + musik latar.
- Konsep kunci: setiap asset hidup dengan **deskripsi AI-friendly** (ditulis manual oleh pengguna di UI — v1, LLM opsional di v2) + **embedding vektor** yang dicari lewat cosine similarity di atas SQLite + numpy.
- Tidak ada video *generation* (diffusers/torch) dan tidak ada vision LM. Generate/missing asset tidak ada — **library only**.
- Semua pemrosesan berjalan di CPU mesin lokal (feat: arsitektur aarch64, tanpa GPU).

### Alur inti

```
Narasi teks bebas
  → plan: LLM teks memecah jadi scene[] (narration = potongan asli + search_query visual + duration_sec)
  → search: embed local tiap search_query scene → cosine ke embedding aset → top-k per scene
  → compose: pilih/urut aset, tentukan durasi & transisi
  → render: ffmpeg (9:16 crop/scale, zoompan utk foto, concat, drawtext, amix musik)
  → MP4 final + unduh via web
```

## 2. Goals / Non-goals

### Goals (v1)
- Web UI untuk: upload aset, lihat/kelola daftar aset, tulis deskripsi AI, buat video dari narasi, pantau job render, unduh hasil.
- Pipeline aset: ingest (upload) → describe (manual) → embed (lokal) → searchable.
- Retrieval berbasis vektor (cosine) atas deskripsi aset berbahasa Indonesia.
- Render ffmpeg lokal untuk output 9:16 dengan teks overlay & musik latar.
- Backend **FastAPI**, frontend **server-rendered (Jinja2 + vanilla JS)**, tanpa build step / tanpa node.

### Non-goals (tidak termasuk v1)
- Deskripsi aset **ditulis manual** oleh pengguna (tanpa vision LM / OCR). LLM helper untuk deskripsi (draft + review) = **v2**.
- Video generation via remote API (mis. Veo/Replicate) — aset hanya dari DAM.
- Download/download aset otomatis saat mencari (missing → pakai yang mirip atau lewati).
- LLM lokal / GPU acceleration.
- Multi-user, login, otorisasi.
- Audio asset sebagai bagian retrieval; musik latar dari folder khusus, tidak masuk RAG.
- TTS voiceover narasi.
- Deploy container/remote (v2).
- Import CLI/folder/Immich (v2).

## 3. User stories

1. **Ingest**: pengguna upload gambar/video lewat halaman web (drag-drop). File tersimpan + metadata dasar + thumbnail dibuat; deskripsi masih kosong (status `empty`).
2. **Understand aset**: pengguna mengisi deskripsi AI-friendly (kalimat + tags) di halaman detail. Aseett tanpa deskripsi **tidak ikut pencarian**. Setelah terisi, trigger *embed*.
3. **Search (internal)**: pipeline mencari aset relevan untuk tiap scene berdasarkan cosine ke narasi scene.
4. **Build video**: pengguna menulis narasi, melihat hasil rencana scene (text + aset terpilih dengan preview thumbnail), membuat beberapa variasi durasi/aspek, lalu memicu render dan menunggu status job.
5. **Result**: job render selesai → video MP4 tampil di halaman hasil dan bisa diunduh; job gagal menampilkan error ffmpeg.

## 4. Arsitektur komponen

```
+---------------------------- Browser ----------------------------+
|  Dashboard · Upload · Assets · Detail asset · Editor narasi ·   |
|  Job status · Hasil video              (Jinja2 + vanilla JS)     |
+-----------------------------------------------------------------+
                          │ HTTP (uvicorn, localhost)
+------------------------------- FastAPI --------------------------+
|  Routes: / , /assets, /assets/{id}, /upload, /build,            |
|          /jobs/{id}, /jobs/{id}/result, /assets/{id}/embed, ...  |
|  BackgroundWorker: job queue in-process (thread pool)            |
+-----------------------------------------------------------------+
   │                 │                │                │
   ▼                 ▼                ▼                ▼
 ingest          describe          embed          render
 (simpan file    (MANUAL: fitur    (model lokal    (ffmpeg subprocess
  ke assets/,     default pengguna  CPU): teks       filter_complex:
  generate thumb  menulis kalimat   deskripsi+tag    crop/scale 9:16,
  & metadata      + tags di UI;     → vektor[]      zoompan, concat,
  sidecar JSON)   LLM helper=v2)                   drawtext, amix)
                            │
                            ▼
                       search (cosine numpy atas .npy + query
                               di sqlite metadata)
```

- **in-process job**: render & (optional) embed bisa lama → jalankan di thread pool, simpan status di tabel `jobs`, UI polling tiap beberapa detik. Cukup untuk single-user localhost.
- **LLM remote**: melalui interface OpenAI-compatible (host + key via env). Agnostik provider: OpenAI / Gemini / DeepSeek / Ollama (OpenAI-compatible). Posisi v1: hanya untuk `plan` (pecah narasi); `describe` tetap manual.
- **Semua persistensi lokal** di `data/` (default; override via env `VIDGENIE_DATA_DIR`): `assets/` (media asli), `sidecars/<id>.json` (metadata aset), `thumbs/`, `vectors/`, `vidgenie.db`.

## 5. Data model

### Sidecar metadata per aset: `data/sidecars/<id>.json`
```json
{
  "id": "uuid",
  "filename": "beach-sunset.mp4",
  "rel_path": "<id>.mp4",
  "type": "image|video",
  "mime": "video/mp4",
  "mtime": "...",
  "size_bytes": 0,
  "width": 1920,
  "height": 1080,
  "duration_sec": 12.0,
  "thumb": "<id>.jpg",
  "tags": ["pantai", "senja"],
  "description": "Klip video pantai saat senja, ...",
  "description_status": "empty|filled",
  "embedding_id": "<id>",
  "embedding_status": "pending|ready|error",
  "created_at": "...",
  "updated_at": "..."
}
```

### Tabel SQLite `vidgenie.db` (v2; v1 memakai sidecar JSON)
- `assets(...)` — ringkasan untuk UI; v1 sumber utama = sidecar JSON.
- `jobs(id, kind[build|embed], status[queued|running|done|error], progress, error, video_path, created_at, finished_at)` — describe tidak via job (penyimpanan manual instan).
- `scenes(id, job_id, index, narration_text, search_query, asset_id, duration_sec, status)` — hasil rencana scene per job.
- `settings(key, value)` — mis. path musik latar, aspek output.

### Vektor: `data/vectors/<asset_id>.npy`
- 1 baris float32 per aset (dari model embedding teks deskripsi + tag).
- Dictionary id→row diindeks secara efisien lewat `assets.embedding_id`.
- Search = cosine antara query vector dan seluruh baris (numpy), ambil top-k. Skala puluhan ribu aset dalam ratusan ms di CPU.

## 6. Halaman & rute web

| Route | Fungsi |
|---|---|
| `GET /` | Dashboard: statistik aset, job terakhir |
| `GET /assets` | Daftar aset (filter type, status description/embed) |
| `POST /upload` | Upload file → ingest + thumbnail, deskripsi status `empty` |
| `GET /assets/{id}` | Detail: preview, metadata, editor deskripsi/tags manual, tombol re-embed |
| `POST /assets/{id}` | Simpan edit manual (deskripsi + tags) |
| `POST /assets/{id}/embed` | Trigger embed (vektor) per aset |
| `GET /build` | Form narasi + konfigurasi (asal musik, durasi scene) |
| `POST /build` | Plan + compose (LLM + search) → simpan job, render |
| `GET /jobs/{id}` | Status kemajuan (polling 2 s) |
| `GET /jobs/{id}/result` | Halaman hasil: video player, unduh MP4, daftar scene & aset terpakai |

## 7. Pipeline teknis

### 7.1 describe (manual — non-vision, non-LLM)
- Penulis: **pengguna melalui UI** (halaman detail aset). Upload tidak otomatis menghasilkan deskripsi.
- Format yang diharapkan (guideline di UI): kalimat deskriptif AI-friendly yang menyebut isi, subjek, aksi, suasana, komposisi — dalam Bahasa Indonesia — plus daftar `tags`.
- Status `empty` → aset **tidak di-embed** dan tidak ikut pencarian; status `filled` setelah disimpan.
- LLM helper (draft dari metadata/filename lalu direview) hanya dipertimbangkan di v2 — tetap non-vision.

### 7.2 embed (lokal CPU)
- **Runtime (hasil SPIKE-001): `fastembed` (ONNX Runtime)** — wheel `onnxruntime 1.30.0 cp314-manylinux_2_28_aarch64` tersedia dan terverifikasi berjalan di aarch64 + Python 3.14.
- **Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** (dim 384, ~0.22 GB, multilingual ≈50 bahasa termasuk Indonesia). Terverifikasi: relevansi Indonesia bagus, throughput ≈30 doc/s CPU.
- Catatan: `intfloat/multilingual-e5-small` (target draft lama) **tidak** didukung fastembed; `multilingual-e5-large` (2.24 GB) terlalu berat untuk v1.
- Model di-cache ke direktori data proyek (parameter `cache_dir`), bukan default user home.
- Persist vektor sebagai `float32` (output fastembed `float64` → cast saat menyimpan `.npy`).
- Fallback (bila fastembed bermasalah di mesin tertentu): `sentence-transformers` via torch — wheel `torch cp314-manylinux_2_28_aarch64` juga ada di PyPI (2.14.0), tapi berat (instal ~GB); gunakan hanya jika perlu.
- Query embedding dihasilkan dari teks narasi scene; dokumen embedding dari deskripsi+tag aset.

### 7.3 plan + search
- `plan`: LLM teks memecah narasi → JSON `[{narration, search_query, duration_sec}]`.
  - `narration` = **potongan narasi asli** (LLM hanya menandai batas potongan, tidak parafrase) — dipakai sebagai teks overlay drawtext.
  - `search_query` = cue visual ringkas (subjek, aksi, suasana, komposisi dalam Bahasa Indonesia) yang dipakai untuk embedding/retrieval; narasi non-visuinal (cerita/dialog) dipetakan ke subjek visual.
  - `duration_sec`: clamp 2–12 s.
  - Prompt dilengkapi few-shot (1 contoh JSON valid); output dibatasi `max_tokens`; default model ringan (task ini ringan), fallback ke model kecil bila model utama gagal.
- `search`: embedding tiap `search_query` → cosine top-k aset (hanya yang `is_searchable` & `embedding_status=ready`) → pilih aset terbaik, cegah reuse aset yang sama terlalu dekat, wajibkan tiap scene ≥1 aset; skor rendah → lewati/pakai caption-only (narasi tampil, aset generic/continue).
- `compose`: elemen per scene = `{asset, caption=narration, duration_sec}`.

### 7.4 render (ffmpeg, CPU)
Output kunci: **9:16 vertikal, 720p (720x1280)**. Langkah per scene:
- **video**: `scale=-2:1280` lalu `crop=720:1280` (center), saran frame 30fps.
- **image**: `zoompan` (slow zoom masuk/keluar) dengan durasi scene.
- **concat**: `concat`/`xfade` antar scene (default crossfade 0.3 s).
- **teks overlay**: `drawtext` narasi per scene (posisi bawah, gaya dari config).
- **musik**: file dari folder khusus (config, mis. `assets/music/<track>.mp3`) → `loop`/`atrim` sesuai durasi total, volume turun (dck) sebagai latar, `amix`/`amovie`. Tanpa musik → file dummy/aac silent.
- Command dibangun sebagai `filter_complex` besar; ditulis ke `render.log` saat job error.

### 7.5 thumbnail
Pillow/ffmpeg menghasilkan `thumbs/<id>.jpg` untuk preview daftar aset & preview scene.

## 8. Stack & dependensi

- Runtime: Python (sistem 3.14; wheel embedding tersedia untuk 3.14 — SPIKE-001).
- Dep inti: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`, `pydantic`, `numpy`, `Pillow`.
- Embedding: **`fastembed`** (ONNX Runtime) + model `paraphrase-multilingual-MiniLM-L12-v2`; fallback `sentence-transformers` (torch) bila perlu.
- Sistem: `ffmpeg` (via `apt-get install ffmpeg`).
- LLM: interface OpenAI-compatible, key via env (`VIDGENIE_LLM_BASE_URL`, `VIDGENIE_LLM_API_KEY`); model utama (`VIDGENIE_LLM_MODEL`, default ringan) + model fallback lebih kecil (`VIDGENIE_LLM_MODEL_FALLBACK`) via config.

## 9. Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Wheel embedding aarch64 + Python 3.14 tidak tersedia | **TERVERIFIKASI ADA (SPIKE-001)**: `fastembed`+`onnxruntime 1.30.0` cp314-aarch64 jalan; model multilingual dipilih; fallback torch cp314-aarch64 juga tersedia. Abstraksi `embedding.py` tetap dipisah agar swap model/runtime mudah |
| `filter_complex` rumit & mudah salah | Bangun renderer iteratif: scene tunggal → multi-scene → +teks → +musik; log ffmpeg detail; flag dry-run untuk melihat command |
| JavaSript vanilla berantakan | Pisah per halaman `<script>` kecil; komunikasi via API endpoint + polling status |
| LLM output tidak valid JSON (plan) / rate limit / timeout | Parse defensif berlapis: strip fence → regex → fallback model kecil → heuristik pecah kalimat; retry eksponensial hanya untuk 429/5xx; timeout & `max_tokens` per request |
| Biaya & latensi LLM remote | Task `plan` ringan → model kecil; `narration` = potongan narasi asli (bukan parafrase, hemat token); output dibatasi `max_tokens`; cache opsional per hash narasi |
| Skala aset besar (embed semua) | Embed async per aset; progress per-aset; tidak memblok UI |

## 10. Roadmap

- **v1 (ini)**: lokal, single-user; upload web; deskripsi **manual** + embed; build dari narasi; render 9:16; musik dari folder; teks overlay.
- **v2 (kandidat)**: LLM-assist deskripsi (draft + review, tetap non-vision); musik & audio sebagai aset retrieval; TTS voiceover; import folder/CLI; dukungan Import asset dari Immich (RAG sidecar); deploy container/remote; multi-user/auth; potong scene & pilih asset di UI lebih granular.