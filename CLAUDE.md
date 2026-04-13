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
Upload/YouTube ingest → Whisper transcription → Claude clip analysis → Tier 1 render (ffmpeg) → Tier 2 production (captions + B-roll composite).

### Backend (FastAPI + SQLite)

| File | Responsibility |
|------|---------------|
| `main.py` | App entry, CORS, router registration, lifespan (DB init + SFX seed) |
| `config.py` | Storage paths, Whisper chunk limits, analysis window sizes |
| `database.py` | SQLite schema, all CRUD — single source of truth for DB |
| `services/transcription.py` | ffmpeg audio extract → Whisper `verbose_json` (chunked, word timestamps) |
| `services/analysis.py` | Windowed Claude analysis → clip candidates with scoring |
| `services/rendering.py` | Tier 1 ffmpeg clip cutting (16:9) |
| `services/reframe.py` | Scene detection + face tracking → 9:16 vertical render |
| `services/captions.py` | Deepgram word-level SRT generation (German-accurate capitalization) |
| `services/styled_captions.py` | SRT → ASS + ffmpeg caption burn; libass when available, drawtext fallback |
| `services/broll.py` | Claude + Pexels B-roll suggestion, scoring, download, ffmpeg compositing |
| `services/production.py` | Tier 2 pipeline: captions → B-roll suggest → auto-approve → composite |

### B-roll pipeline (`services/broll.py`)
- `suggest_broll(clip_id)` — sends word-timestamped transcript to Claude → filmability test prompt → Pexels multi-query search with `_score_video` scoring + slug relevance check → downloads + stores in `broll_suggestions`
- `composite_broll(clip_id)` / `_run_composite()` — reads approved suggestions, calls `_build_composite_filter()`, runs ffmpeg
- `_build_composite_filter()` — builds `filter_complex` using per-segment `fade=out`/`fade=in` + `concat`. **No xfade** (removed: ffmpeg 8.1 filter negotiation breaks `settb` workaround). A-roll trim end is extended by `fade_dur` so the fade-out starts exactly at `start_sec`, not before it.
- Word-level timestamps from Whisper are stored in `transcripts.words_json` (absolute). `suggest_broll` subtracts `clip["start_sec"]` to get clip-relative times before storing in `broll_suggestions.start_word`/`end_word`.

### Caption pipeline (`services/captions.py` → `services/styled_captions.py`)
- Deepgram nova-2 with `punctuate=true`. German noun capitalization comes from the `transcript` string (capitalized), not the `words` array (lowercase) — cross-referenced by token index.
- Chunking: `max_chars=14`, `_MIN_DURATION=3/30s`. Single words ≥ 3 frames or ending a sentence stand alone; otherwise paired.
- 9:16 vertical: captions positioned at 57.5% from top via `\an5\pos(cx,cy)` in ASS. 16:9: standard bottom position.

### Production pipeline (`services/production.py`)
- `produce_clip(clip_id)` runs sequentially: burn captions → suggest B-roll → auto-approve → composite 16:9 → composite 9:16
- `production_step` column written at each stage; cleared on completion; polled by frontend every 3s

### Database schema notes
- `database.py` uses `ALTER TABLE … ADD COLUMN` with `try/except` for forward migrations — new columns are safe to add without dropping the DB.
- `clip_candidates` key columns: `preview_path` (16:9 render), `vertical_path` (9:16), `captioned_path`, `broll_path`, `produced_path`, `production_status`, `production_step`
- `broll_suggestions`: `start_sec`/`end_sec` are clip-relative (seconds from clip start), `start_word`/`end_word` for logging/debug

### Frontend (React 18 + Vite + TypeScript)
- Single-page app in `frontend/src/`. Views in `views/`, shared components in `components/`.
- API client in `frontend/src/api.ts` — update the `Clip` interface there when adding DB columns surfaced by GET endpoints.
- No routing library; view switching is handled in `App.tsx`.

## Environment variables

```
OPENAI_API_KEY=...       # Whisper transcription
ANTHROPIC_API_KEY=...    # Claude analysis + B-roll prompts
DEEPGRAM_API_KEY=...     # Caption SRT generation
PEXELS_API_KEY=...       # B-roll video search
```

## Known constraints
- Python 3.9 — no `X | Y` union type syntax (use `Optional[X]` or omit annotations)
- ffmpeg must be on `PATH` (`brew install ffmpeg`); libass optional but used when present
- SQLite is single-file (`clip_engine.db`, project root); no migrations tool — schema changes go in `init_db()` via `ALTER TABLE`
