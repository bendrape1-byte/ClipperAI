# ClipperAI

Upload a podcast MP4 (or paste a YouTube URL) → transcribe with Whisper → find clip candidates with Claude → render clips → generate captions and 9:16 vertical versions.

## Prerequisites

- Python 3.9+
- Node 18+
- ffmpeg on PATH (`brew install ffmpeg`)

## Environment variables

Create a `.env` file or export these before starting:

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
DEEPGRAM_API_KEY=...   # only needed for SRT generation
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
│   ├── analysis.py          # Claude clip analysis, windowing, deduplication
│   ├── rendering.py         # ffmpeg clip cutting (16:9)
│   ├── reframe.py           # Scene detection + face tracking + 9:16 rendering
│   ├── captions.py          # Deepgram SRT generation
│   └── youtube.py           # yt-dlp download
├── routes/
│   ├── media.py             # /api/media/* endpoints
│   ├── clips.py             # /api/clips/* endpoints
│   └── profiles.py          # /api/profiles/* endpoints
├── frontend/                # React 18 + Vite + TypeScript
└── storage/
    ├── originals/           # uploaded / downloaded MP4s
    ├── audio/               # extracted MP3s
    ├── clips/               # rendered 16:9 clips
    ├── vertical/            # rendered 9:16 clips
    └── captions/            # generated SRT files
```

## API endpoints

### Media

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/media/upload` | Upload an MP4 (multipart, field `file`) |
| `POST` | `/api/media/youtube` | Ingest a YouTube URL (`{ url, profile_id? }`) |
| `GET`  | `/api/media/{id}` | Full metadata for a media asset |
| `GET`  | `/api/media/{id}/status` | Current status string |
| `GET`  | `/api/media/{id}/transcript` | Full transcript with segments |
| `POST` | `/api/media/{id}/analyze` | Start clip analysis (`{ context?, profile_id? }`) |
| `GET`  | `/api/media/{id}/clips` | List all clip candidates |
| `POST` | `/api/media/{id}/render-all` | Queue 16:9 render for all clips |
| `POST` | `/api/media/{id}/generate-all-srt` | Queue SRT generation for all rendered clips |
| `POST` | `/api/media/{id}/render-all-vertical` | Queue 9:16 render for all rendered clips |

**Media status lifecycle:**
`uploaded` / `downloading` → `processing` → `transcribing` → `transcribed` → `analyzing` → `ready` (or `error`)

### Clips

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/clips/{id}/render` | Queue 16:9 render for one clip |
| `POST` | `/api/clips/{id}/extend` | Adjust start/end (`{ start_delta, end_delta }`) and re-render |
| `GET`  | `/api/clips/{id}/download` | Download rendered 16:9 clip |
| `POST` | `/api/clips/{id}/generate-srt` | Queue SRT generation |
| `GET`  | `/api/clips/{id}/download-srt` | Download SRT file |
| `POST` | `/api/clips/{id}/render-vertical` | Queue 9:16 vertical render |
| `GET`  | `/api/clips/{id}/download-vertical` | Download rendered 9:16 clip |

### Profiles

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/profiles` | Create a clip profile |
| `GET`  | `/api/profiles` | List all profiles |
| `GET`  | `/api/profiles/{id}` | Get one profile |
| `PUT`  | `/api/profiles/{id}` | Update a profile |

## Storage

Database: `clip_engine.db` (SQLite, auto-created on first run).
All media files live under `storage/` (auto-created, gitignored).
