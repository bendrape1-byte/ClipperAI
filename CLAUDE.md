# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Backend** (run from project root, venv activated):
```bash
source .venv/bin/activate
uvicorn main:app --reload          # start dev server on :8000
uvicorn main:app --reload --log-level debug   # with verbose logs
```

**Frontend** (run from `frontend/`):
```bash
npm run dev      # Vite dev server on :5173
npm run build    # TypeScript check + production build
```

**Dependencies** (ask before adding new ones):
```bash
pip install -r requirements.txt
cd frontend && npm install
```

**No test suite exists** — validate by running the server and using the UI or `/docs`.

## Architecture

### Overview
This repo has been stripped to its **core spine**:

**Upload/YouTube ingest → Whisper transcription → Claude clip analysis → 16:9 render (ffmpeg).**

Caption burning, B-roll, 9:16 vertical reframe, sound effects, and per-show clip profiles have
all been removed. Rebuilding the analysis/rendering core is the next stage — keep changes here
to the four-step spine.

### Backend (FastAPI + SQLite)

| File | Responsibility |
|------|---------------|
| `main.py` | App entry, CORS, router registration, lifespan (DB init + storage dirs) |
| `config.py` | Storage paths, Whisper chunk limits, analysis window sizes |
| `database.py` | SQLite schema, all CRUD — single source of truth for DB |
| `services/transcription.py` | ffmpeg audio extract → Whisper `verbose_json` (chunked, word timestamps) |
| `services/analysis.py` | Windowed Claude analysis → clip candidates with scoring → Tier-1 16:9 render |
| `services/rendering.py` | ffmpeg clip cutting (16:9) |
| `services/youtube.py` | yt-dlp download of a YouTube source |
| `routes/media.py` | `/api/media/*` — upload, youtube, status, transcript, analyze, clips, render-all, download-approved |
| `routes/clips.py` | `/api/clips/*` — render, extend, download (16:9), get, approve, reject |

### Pipeline flow
1. **Ingest** — `POST /api/media/upload` (MP4) or `POST /api/media/youtube`. Stored in
   `media_assets`; an audio-extraction background task kicks off immediately.
2. **Transcribe** — `services/transcription.py` extracts audio and runs Whisper (chunked, with
   word timestamps); result stored in `transcripts` (`transcript_json` + `words_json`).
3. **Find** — `POST /api/media/{id}/analyze` runs `services/analysis.py`: the transcript is split
   into overlapping windows (`WINDOW_SIZE`/`WINDOW_OVERLAP`), each sent to Claude, hook
   timestamps are corrected against the word data, candidates deduplicated, then stored in
   `clip_candidates`. An optional freeform `context` string can be passed to inform scoring.
4. **Cut 16:9** — analysis then drives Tier-1 rendering: `_render_tier1` calls `render_clip` per
   candidate (up to 3 workers), writing `preview_path`. The clips page polls until ready.

### Database schema notes
- `database.py` uses `ALTER TABLE … ADD COLUMN` with `try/except` for forward migrations.
- **The schema is intentionally frozen during the strip.** The tables and columns belonging to
  the removed features (`clip_profiles`, `broll_suggestions`, `sfx_library`, and the
  `vertical_*` / `captioned_*` / `broll_*` / `produced_*` / `srt_path` / `production_*` /
  `profile_id` columns) are still created by `init_db()` but are now dead/unused. Leave them in
  place — the next stage decides what to keep.
- Active `clip_candidates` columns: `start_sec`, `end_sec`, `title`, `hook`, `reasoning`,
  `score`, `transcript_excerpt`, `preview_path` (16:9 render), `status`.

### Frontend (React 18 + Vite + TypeScript)
- Single-page app in `frontend/src/`. Views in `views/`, shared components in `components/`.
- Three views, switched in `App.tsx` (no router): `upload` → `processing` → `clips`.
- API client in `frontend/src/api.ts` — keep the `Clip` interface in sync with the fields the
  backend actually produces.

## Environment variables

```
OPENAI_API_KEY=...       # Whisper transcription
ANTHROPIC_API_KEY=...    # Claude clip analysis
```

## Known constraints
- Python 3.9 — no `X | Y` union type syntax (use `Optional[X]` or omit annotations)
- ffmpeg must be on `PATH` (`brew install ffmpeg`)
- SQLite is single-file (`clip_engine.db`, project root); no migrations tool — schema changes go in `init_db()` via `ALTER TABLE`
