# CLAUDE.md

Guidance for Claude Code when working on this repository.

## What this is

A Claude Code **skill**. The repo root is the skill folder: editors clone it into
`~/.claude/skills/clipper` and Claude follows `SKILL.md`. There is no server, no database, no build step
and no API key.

**Pipeline:** local Whisper transcription → Claude picks clips in-session → editor reviews in a
browser page that plays straight from the source file → export as a Premiere timeline or lossless clip
files for CapCut. Nothing is ever rendered or re-encoded.

## Files

| File | Responsibility |
|------|---------------|
| `SKILL.md` | The instructions Claude follows, including the verbatim clip-scoring brief |
| `scripts/setup.py` | Detects the machine, picks backend + model, prints install commands, writes `config.json` |
| `scripts/transcribe.py` | File or YouTube URL → `transcript.json` (segments + word timestamps) and `transcript.txt` |
| `scripts/build_review.py` | `candidates.json` → sentence-snapped, de-duplicated `clips.json` + `review.html` |
| `scripts/review_template.html` | The review UI: one static file, vanilla JS, no dependencies |
| `scripts/export.py` | `approved.json` → `premiere.xml` (FCP7 XML) and/or stream-copied `clips/*` |
| `scripts/_tools.py` | Adds the skill's private ffmpeg / yt-dlp folders (from `config.json`) to `PATH` |
| `scripts/test_clipper.py` | Self-check for boundary matching and timecode maths |
| `README.md` | Editor-facing guide, plus the install steps and troubleshooting table Claude follows |

Jobs live outside the repo in `~/Movies/Clipper/<name>/`.

## Commands

```bash
python3 scripts/setup.py            # show the plan for this machine
python3 scripts/setup.py --write    # save config.json once everything is installed
python3 scripts/test_clipper.py     # run after touching build_review.py or export.py
.venv/bin/python scripts/transcribe.py "<file or URL>"
python3 scripts/build_review.py "<job>"
python3 scripts/export.py "<job>" --premiere --capcut
```

Validate UI changes by rebuilding a real job's `review.html` and loading it from disk in Chrome.

## Constraints

- Only `transcribe.py` runs in the venv. Every other script is stdlib-only and must run on the system
  `python3` (keep it 3.9-compatible: no `X | Y` unions).
- Ask before adding a dependency. The review page must keep working offline, opened via `file://`.
- Never add a step that encodes video. Previews play the source; CapCut export is `-c copy`.
- The scoring brief in `SKILL.md` is copied word for word from the old app. Change it deliberately.
- `ffmpeg`, `ffprobe` and `yt-dlp` are used from `PATH` when present. Otherwise `setup.py` installs
  a private `static-ffmpeg` into the venv, so no Homebrew or admin rights. yt-dlp is always the
  standalone build in `bin/`, even when one is on `PATH`: it updates itself (`transcribe.py` runs
  `-U` and retries once on failure), while a four-month-old Homebrew copy got HTTP 403 from YouTube
  in testing.
- Links go to the editor's 4K Video Downloader first (macOS): `download_4k()` in `transcribe.py`
  copies the link, clicks the app's Paste Link menu item via System Events (found by its Cmd+V
  shortcut, so it is language-independent) and polls the app's SQLite database for the finished
  file (`download_item.state` 0 = running, 1 = done). The app has no API; this is the whole
  integration. yt-dlp is the fallback.
- A new failure mode an editor can hit gets a row in the README troubleshooting table.
- Hardware thresholds in `setup.py` are first guesses, measured only on a 24 GB Apple Silicon Mac.
  A fresh install was simulated there with the stock `/usr/bin/python3` (3.9) and no Homebrew.

## Direction

After a few rounds of editor feedback the review page becomes a Mac app (alongside the web page) with
local storage, and later gains a real timeline editor. Keep `review_template.html` self-contained so it
can be wrapped in a web view; do not build any of that until asked.

## Leftovers

`storage/`, `clip_engine.db`, `start.command` and the `.mp4` in the root belong to the old FastAPI app.
They are git-ignored and unused. Do not delete them without asking.
