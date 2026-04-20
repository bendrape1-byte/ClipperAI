# ClipperAI — Partner Troubleshooting Context

Paste this entire file as your first message whenever you start a new Claude Code session.

---

## Who I am

My name is Phelano. I am not a developer. I run this app locally on my Mac to use it — I do not write or change code. When something breaks, I need step-by-step instructions in plain language, telling me exactly what to type and where.

**Never ask me to edit code files.** Only help me troubleshoot why the app is not running or not behaving correctly.

## What this app is

ClipperAI is a local web app that takes a podcast video, transcribes it, finds good clips with AI, and renders them. I access it in my browser at `http://localhost:5173`.

## My setup

- Mac: `/Users/phelanoeffner`
- Project folder: `~/ClipperAI` (not in Documents — moved out of iCloud)
- To start the app: double-click `~/ClipperAI/start.command` in Finder
- To stop the app: close the Terminal window that opens
- Backend runs at `http://localhost:8000`
- Frontend runs at `http://localhost:5173`
- Python venv is at `~/ClipperAI/.venv`
- API keys are stored inside `~/ClipperAI/start.command` (gitignored, never committed)
- No `.env` file — keys are exported directly in `start.command`

## Tech stack (for your reference, I don't need to understand this)

- Backend: Python 3.9, FastAPI, SQLite (`clip_engine.db`), uvicorn
- Frontend: React 18, Vite, TypeScript
- Transcription: OpenAI Whisper
- Clip analysis: Anthropic Claude
- Captions: Deepgram
- B-roll: Pexels API
- Video processing: ffmpeg (installed via Homebrew)

## How to start/stop correctly

**Start:** Double-click `start.command` in Finder. First launch takes 3–5 min (installing dependencies). After that, browser opens automatically to `http://localhost:5173`.

**Stop:** Close the Terminal window. Both servers shut down automatically.

**If the app won't start:** Check that the Terminal window from a previous session is fully closed first. Two instances can't run at the same time.

## Known issues and their fixes

### iCloud conflict (already resolved)
Project was moved from `~/Documents/ClipperAI` to `~/ClipperAI` to avoid iCloud Drive interfering with file reads. Do not move it back to Documents.

### Gatekeeper block on first run (already resolved)
Fixed by right-clicking `start.command` → Open the first time. Works normally now.

### Port already in use
If the app says port 8000 or 5173 is already in use, a previous session did not shut down cleanly. Fix:
```
lsof -ti:8000 | xargs kill -9
lsof -ti:5173 | xargs kill -9
```
Then double-click `start.command` again.

## Current unresolved issue

**400 Bad Request when uploading an .mp4 file.** The file is confirmed to be .mp4. The backend log shows `POST /api/media/upload HTTP/1.1 400 Bad Request` but no traceback. This has not been diagnosed yet. When helping with this, ask me to open the browser DevTools (Cmd+Option+I → Network tab) and copy the full response body of the failed upload request.

## How to get updates from Ben

When Ben says he pushed an update, open Terminal and run:
```
cd ~/ClipperAI && git pull
```
Then start the app normally.

## Rules for helping me

1. Give me exact commands to paste — never say "run the appropriate command"
2. Tell me whether to run it in Terminal or do it in Finder
3. Explain what the command does in one simple sentence before I run it
4. Point out the most likely thing that could go wrong before I try it
5. Never tell me to edit a code file
