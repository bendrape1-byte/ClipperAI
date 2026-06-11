# ClipperAI

Upload a podcast MP4 (or paste a YouTube URL) → transcribe with Whisper → find clip candidates with Claude → cut them as 16:9.

## Prerequisites

- Python 3.9+
- Node 18+
- ffmpeg on PATH (`brew install ffmpeg`)

## Environment variables

Create a `.env` file or export these before starting:

```
OPENAI_API_KEY=...       # Whisper transcription
ANTHROPIC_API_KEY=...    # Claude clip analysis
```

## Setup and run

**Mac Terminal** — from the project folder:

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend (separate terminal, same folder)
cd frontend
npm install
npm run dev
```

Backend: `http://localhost:8000` · API docs: `http://localhost:8000/docs`
Frontend: `http://localhost:5173`

## File structure

```
ClipperAI/
├── main.py                  # FastAPI app, lifespan, CORS, router includes
├── config.py                # Storage paths and tuning constants
├── database.py              # SQLite schema and all CRUD functions
├── requirements.txt
├── services/
│   ├── transcription.py     # ffmpeg audio extraction + Whisper transcription
│   ├── analysis.py          # Claude clip analysis, windowing, dedup, 16:9 render
│   ├── rendering.py         # ffmpeg clip cutting (16:9)
│   └── youtube.py           # yt-dlp download
├── routes/
│   ├── media.py             # /api/media/* endpoints
│   └── clips.py             # /api/clips/* endpoints
├── frontend/                # React 18 + Vite + TypeScript
└── storage/
    ├── originals/           # uploaded / downloaded MP4s
    ├── audio/               # extracted audio
    └── clips/               # rendered 16:9 clips
```

## API endpoints

### Media

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/media/upload` | Upload an MP4 (multipart, field `file`) |
| `POST` | `/api/media/youtube` | Ingest a YouTube URL (`{ url }`) |
| `GET`  | `/api/media/{id}` | Full metadata for a media asset |
| `GET`  | `/api/media/{id}/status` | Current status string |
| `GET`  | `/api/media/{id}/transcript` | Full transcript with segments |
| `POST` | `/api/media/{id}/analyze` | Start clip analysis (`{ context? }`) |
| `GET`  | `/api/media/{id}/clips` | List all clip candidates |
| `POST` | `/api/media/{id}/render-all` | Queue 16:9 render for all clips |
| `GET`  | `/api/media/{id}/download-approved` | Download all approved clips as a zip |

**Media status lifecycle:**
`uploaded` / `downloading` → `processing` → `transcribing` → `transcribed` → `analyzing` → `rendering` → `ready` (or `error`)

### Clips

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/clips/{id}/render` | Queue 16:9 render for one clip |
| `POST` | `/api/clips/{id}/extend` | Adjust start/end (`{ start_delta, end_delta }`) and re-render |
| `GET`  | `/api/clips/{id}/download` | Download rendered 16:9 clip |
| `GET`  | `/api/clips/{id}` | Get one clip candidate |
| `POST` | `/api/clips/{id}/approve` | Mark a clip approved |
| `POST` | `/api/clips/{id}/reject` | Mark a clip rejected |

## Storage

Database: `clip_engine.db` (SQLite, auto-created on first run).
All media files live under `storage/` (auto-created, gitignored).
