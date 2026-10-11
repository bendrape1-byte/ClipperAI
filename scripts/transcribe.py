"""Source video (local file or YouTube URL) -> job folder with transcript.json + transcript.txt.

Run with the skill's venv python (see config.json "python"):
  python transcribe.py SOURCE              local Whisper with word timestamps
  python transcribe.py SOURCE --srt FILE   no Whisper: use an existing .srt/.vtt
  python transcribe.py URL                 hands the link to 4K Video Downloader when it is installed (macOS),
                                           otherwise downloads with yt-dlp
  python transcribe.py URL --no-4k --best  yt-dlp, top format instead of H.264
  python transcribe.py SOURCE --prompt "Heidi Reichinnek, Indymedia"   spell these names right
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from _tools import use_local_tools

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # keep the output short enough to read

SKILL = Path(__file__).resolve().parent.parent
use_local_tools()
JOBS = Path.home() / "Movies" / "Clipper"


APP4K = "4K Video Downloader+"
PASTE_LINK = '''
tell application "%s" to launch
tell application "System Events"
    repeat 60 times
        if exists (first process whose name is "4kvideodownloaderplus") then exit repeat
        delay 0.5
    end repeat
    delay 3
    tell (first process whose name is "4kvideodownloaderplus")
        repeat with mb in menu bar items of menu bar 1
            repeat with mi in menu items of menu 1 of mb
                try
                    if value of attribute "AXMenuItemCmdChar" of mi is "V" then
                        click mi
                        return "ok"
                    end if
                end try
            end repeat
        end repeat
    end tell
end tell
return "no paste command found"
''' % APP4K


def download_4k(url, log=lambda m: print(m, file=sys.stderr)):
    """Hand the link to 4K Video Downloader the way an editor does: copy it, then trigger the app's
    Paste Link command (found by its Cmd+V shortcut, so the app's language does not matter).
    The app has no API; its download database tells us which file it wrote and when it is done.
    Returns the file, or None when the app is missing or did not take the link. macOS only."""
    data = Path.home() / "Library" / "Application Support" / "4kdownload.com" / APP4K / APP4K
    if sys.platform != "darwin" or not Path("/Applications/%s.app" % APP4K).exists():
        return None

    def items():
        dbs = sorted(data.glob("*.sqlite"), key=lambda f: f.stat().st_mtime)
        if not dbs:
            return []
        con = sqlite3.connect("file:%s?mode=ro" % quote(str(dbs[-1])), uri=True, timeout=5)
        try:
            return con.execute("select id, filename, state from download_item order by id").fetchall()
        except sqlite3.Error:
            return []
        finally:
            con.close()

    last = max([r[0] for r in items()] or [0])
    clipboard = subprocess.run(["pbpaste"], stdout=subprocess.PIPE).stdout
    try:
        subprocess.run(["pbcopy"], input=url.encode())
        r = subprocess.run(["osascript", "-e", PASTE_LINK], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2)  # the app reads the clipboard when the command fires
    finally:
        subprocess.run(["pbcopy"], input=clipboard)
    if r.stdout.strip() != "ok":
        log("4K Video Downloader did not take the link: %s" % (r.stderr.strip() or r.stdout.strip()))
        return None

    DONE, started, seen = 1, time.time(), None
    while True:
        new = [x for x in items() if x[0] > last]
        if not new and time.time() - started > 90:      # it showed a dialog or rejected the link
            log("4K Video Downloader did not start a download within 90 s")
            return None
        if new:
            _, filename, state = new[-1]
            if state != seen:
                log("4K Video Downloader: %s (state %s)" % (Path(filename or "?").name, state))
                seen = state
            f = Path(filename) if filename else None
            if state == DONE and f and f.exists():
                return f
        # ponytail: no overall timeout; a 2-hour 4K video can take a long while. Stop the script to abort.
        time.sleep(2)


def download(url, best):
    # H.264 + AAC plays in every browser and in CapCut.
    # ponytail: YouTube only serves H.264 up to 1080p; --best takes 4K (usually AV1) instead.
    fmt = "bv*+ba/b" if best else "bv*[vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/b"
    # The skill's own copy can update itself; a system-wide yt-dlp usually cannot and goes stale.
    own = SKILL / "bin" / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    ytdlp = str(own) if own.exists() else "yt-dlp"
    cmd = [ytdlp, "-f", fmt, "--merge-output-format", "mp4", "--restrict-filenames", "--no-playlist",
           "-o", str(JOBS / "%(title).80s" / "%(title).80s.%(ext)s"), "--print", "after_move:filepath", url]
    for attempt in (1, 2):
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            return Path(r.stdout.strip().splitlines()[-1])
        if attempt == 1:  # YouTube changes often: a 403 usually just means the downloader is out of date
            subprocess.run([ytdlp, "-U"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sys.exit("YouTube download failed, also after updating yt-dlp:\n%s\n"
             "Ask the user to download the video with 4K Video Downloader and give you the file."
             % r.stderr.strip()[-400:])


def whisper(src, cfg, prompt=None):
    if cfg["backend"] == "mlx":
        import mlx_whisper
        r = mlx_whisper.transcribe(str(src), path_or_hf_repo=cfg["model"], word_timestamps=True, verbose=None,
                                   initial_prompt=prompt)
        segs = [(s["start"], s["end"], s["text"], s.get("words", [])) for s in r["segments"]]
    else:
        from faster_whisper import WhisperModel
        model = WhisperModel(cfg["model"], device=cfg["device"], compute_type=cfg["compute_type"])
        it, _ = model.transcribe(str(src), word_timestamps=True, vad_filter=True, initial_prompt=prompt)
        segs = [(s.start, s.end, s.text,
                 [{"word": w.word, "start": w.start, "end": w.end} for w in (s.words or [])]) for s in it]
    segments = [{"start": float(a), "end": float(b), "text": t.strip()} for a, b, t, _ in segs]
    words = [{"word": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
             for _, _, _, ws in segs for w in ws]
    return segments, words


def from_srt(path):
    ts = r"(\d+):(\d+):(\d+)[,.](\d+)"
    segments, words = [], []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8-sig")):
        m = re.search(ts + r"\s*-->\s*" + ts, block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        text = re.sub(r"<[^>]+>", "", block[m.end():].split("\n", 1)[-1]).replace("\n", " ").strip()
        if not text:
            continue
        segments.append({"start": start, "end": end, "text": text})
        # ponytail: no real word timing in subtitles, so spread words evenly across the line.
        # Cuts land within a subtitle line's length, not on the word.
        toks = text.split()
        step = (end - start) / len(toks)
        words += [{"word": w, "start": start + i * step, "end": start + (i + 1) * step} for i, w in enumerate(toks)]
    return segments, words


def stamp(sec):
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--srt")
    ap.add_argument("--best", action="store_true")
    ap.add_argument("--no-4k", action="store_true", help="skip 4K Video Downloader and use yt-dlp")
    ap.add_argument("--prompt", help="names and terms that occur in the video, to get their spelling right")
    a = ap.parse_args()

    if re.match(r"https?://", a.source):
        src = None if a.no_4k else download_4k(a.source)
        if src:  # 4K Video Downloader keeps the file in its own folder; the job goes next to the others
            job = JOBS / src.stem
        else:
            src = download(a.source, a.best)
            job = src.parent
    else:
        src = Path(a.source).expanduser().resolve()
        if not src.is_file():
            sys.exit("source not found: %s" % src)
        job = JOBS / src.stem
    job.mkdir(parents=True, exist_ok=True)

    if a.srt:
        segments, words = from_srt(a.srt)
    else:
        cfg_path = SKILL / "config.json"
        if not cfg_path.exists():
            sys.exit("no config.json: run setup.py first")
        cfg = json.loads(cfg_path.read_text())
        if cfg["backend"] == "none":
            sys.exit("this machine has no local transcription: pass --srt FILE")
        segments, words = whisper(src, cfg, a.prompt)
    if not segments:
        sys.exit("transcript is empty")

    (job / "job.json").write_text(json.dumps({"source": str(src)}, indent=2))
    (job / "transcript.json").write_text(json.dumps({"segments": segments, "words": words}, ensure_ascii=False))
    (job / "transcript.txt").write_text(
        "\n".join("[%s] %s" % (stamp(s["start"]), s["text"]) for s in segments), encoding="utf-8")
    print(json.dumps({"job": str(job), "source": str(src), "segments": len(segments), "words": len(words),
                      "duration": stamp(segments[-1]["end"])}))


if __name__ == "__main__":
    main()
