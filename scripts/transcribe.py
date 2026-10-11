"""Source video (local file or YouTube URL) -> job folder with transcript.json + transcript.txt.

Run with the skill's venv python (see config.json "python"):
  python transcribe.py SOURCE              local Whisper with word timestamps
  python transcribe.py SOURCE --srt FILE   no Whisper: use an existing .srt/.vtt
  python transcribe.py URL --best          YouTube in the top format instead of H.264
  python transcribe.py SOURCE --prompt "Heidi Reichinnek, Indymedia"   spell these names right
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from _tools import use_local_tools

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")  # keep the output short enough to read

SKILL = Path(__file__).resolve().parent.parent
use_local_tools()
JOBS = Path.home() / "Movies" / "Clipper"


def download(url, best):
    # H.264 + AAC plays in every browser and in CapCut.
    # ponytail: YouTube only serves H.264 up to 1080p; --best takes 4K (usually AV1) instead.
    fmt = "bv*+ba/b" if best else "bv*[vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/b"
    out = subprocess.check_output([
        "yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--restrict-filenames", "--no-playlist",
        "-o", str(JOBS / "%(title).80s" / "%(title).80s.%(ext)s"),
        "--print", "after_move:filepath", url], text=True)
    return Path(out.strip().splitlines()[-1])


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
    ap.add_argument("--prompt", help="names and terms that occur in the video, to get their spelling right")
    a = ap.parse_args()

    if re.match(r"https?://", a.source):
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
