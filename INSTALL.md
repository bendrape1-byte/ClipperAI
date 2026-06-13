# INSTALL — setup guide for Claude Code

**Audience: Claude Code, installing this app on a fresh machine.** Follow this file top to
bottom. It is the authoritative setup guide — prefer it over `README.md` if they disagree.
Detect the user's OS first and use the matching commands.

ClipperAI: upload a podcast MP4 (or paste a YouTube URL) → transcribe with Whisper → find clip
candidates with Claude → cut them as 16:9.

---

## Most likely failure points (read first)

1. **ffmpeg is not on PATH.** The app shells out to `ffmpeg`/`ffprobe`. If `ffmpeg -version`
   fails, transcription and rendering fail. Install it (Step 0) before anything else.
2. **API keys must be in the environment.** The backend reads `OPENAI_API_KEY` and
   `ANTHROPIC_API_KEY` from the shell environment. It does **not** auto-load a `.env` file —
   creating a `.env` alone will silently do nothing. Export them in the same shell that runs
   `uvicorn` (Step 4).
3. **`start.command` is not in the repo.** It is gitignored (it holds secrets). The clone only
   contains `start.command.template`. On macOS you create `start.command` from it (Step 5).

---

## Step 0 — Prerequisites

Check each, install whatever is missing. **Ask the user before installing system packages.**

| Tool | Check | Install (macOS) | Install (Windows) | Install (Linux/Debian) |
|------|-------|-----------------|-------------------|------------------------|
| git | `git --version` | `brew install git` | `winget install Git.Git` | `sudo apt install git` |
| Python 3.9+ | `python3 --version` | `brew install python` | `winget install Python.Python.3.12` | `sudo apt install python3 python3-venv` |
| Node 18+ | `node --version` | `brew install node` | `winget install OpenJS.NodeJS.LTS` | `sudo apt install nodejs npm` |
| ffmpeg | `ffmpeg -version` | `brew install ffmpeg` | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |

> macOS without Homebrew: install it from https://brew.sh first.
> Windows: after `winget install`, open a **new** terminal so PATH updates take effect.

The code targets **Python 3.9** syntax, so any Python ≥ 3.9 works.

---

## Step 1 — Get the code

If not already cloned into the current folder:

```bash
git clone https://github.com/bendrape1-byte/ClipperAI.git
cd ClipperAI
```

If already inside the repo, just stay there. All remaining commands run from the project root.

---

## Step 2 — Backend (Python)

Create a virtual environment, activate it, install dependencies.

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell blocks activation with a script-policy error, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry.

The SQLite database (`clip_engine.db`) and `storage/` folders are created automatically on first
boot — nothing to set up by hand.

---

## Step 3 — Frontend (build once)

The frontend talks to the backend over relative `/api` paths, so once it's **built**, the backend
serves the whole UI on its own port. This means the user runs **one** process and opens **one**
URL — no separate dev server.

```bash
cd frontend
npm install
npm run build
cd ..
```

This produces `frontend/dist/`, which `main.py` serves automatically when present.

---

## Step 4 — API keys

The user needs **their own** two keys (the repo does not and must not contain them):

- `OPENAI_API_KEY` — Whisper transcription — https://platform.openai.com/api-keys
- `ANTHROPIC_API_KEY` — Claude clip analysis — https://console.anthropic.com/settings/keys

**Stop here and ask the user to paste both keys.** Then export them in the shell you will run
`uvicorn` from. **Never commit, log, or echo the key values back.**

**macOS / Linux:**
```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY="sk-..."
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

These last only for the current terminal session. For a permanent setup, use the launcher in
Step 5 (macOS) or have the user re-export them each time / add them to their shell profile.

---

## Step 5 — Run

With the keys exported in this shell:

```bash
uvicorn main:app
```

Then open **http://localhost:8000** in a browser. The API docs are at
http://localhost:8000/docs. Stop the server with `Ctrl+C`.

**macOS convenience launcher (optional but recommended for the user):** create a double-click
launcher so they don't need the terminal next time.
```bash
cp start.command.template start.command
chmod +x start.command
```
Then edit `start.command` and paste the two keys between the quotes on the `OPENAI_API_KEY=""`
and `ANTHROPIC_API_KEY=""` lines. After that the user can launch the app by double-clicking
`start.command` in Finder. It stays gitignored. (Note: the launcher also starts the Vite dev
server on :5173; that's fine, but the built app on :8000 is the simpler URL to use.)

---

## Step 6 — Verify the install

1. `ffmpeg -version` succeeds.
2. Backend boots: `uvicorn main:app` logs `Clip Engine ready.` with no traceback.
3. `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs` returns `200`.
4. Opening http://localhost:8000 shows the ClipperAI upload page.
5. Real end-to-end (uses the user's API credits, so confirm first): upload a short MP4 or paste a
   YouTube URL, wait for transcription → analysis → rendering to reach **ready**, and confirm a
   clip plays. The backend log prints a `boundaries for media_id=…: N/M snapped, …` line during
   analysis — that means the clip-boundary logic ran.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Transcription never starts / 401 from OpenAI | `OPENAI_API_KEY` not exported in the shell running uvicorn. Re-export, restart uvicorn. |
| Analysis resets status to `transcribed` | `ANTHROPIC_API_KEY` missing/invalid. Same fix. |
| `ffmpeg: command not found` in logs | ffmpeg not on PATH. Reinstall (Step 0), open a new terminal. |
| UI loads but every action errors | You ran `uvicorn` without building the frontend, or are opening :5173 without the dev server. Build it (Step 3) and use http://localhost:8000. |
| `ModuleNotFoundError` on boot | venv not activated, or deps not installed. Activate `.venv`, rerun `pip install -r requirements.txt`. |
| Port 8000 in use | Another process holds it. Stop it, or run `uvicorn main:app --port 8010` and open that port. |
