"""
services/styled_captions.py — SRT → ASS conversion and ffmpeg caption burning.

Style: Helvetica Neue Bold (falls back to Arial Bold / Liberation Sans Bold),
       white text, bottom-center, proportional font size, soft 2px drop shadow,
       no outline.  One line at a time; entries longer than 6 words are split
       into proportionally-timed sub-lines.
"""

import functools
import logging
import os
import re
import subprocess
import tempfile

from config import CLIPS_DIR
from database import get_clip_candidate, update_clip_candidate
from services.reframe import get_video_dimensions

logger = logging.getLogger(__name__)

_MAX_WORDS_PER_LINE = 6


# ---------------------------------------------------------------------------
# libass detection
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _has_libass() -> bool:
    """Return True if the installed ffmpeg was compiled with libass (ass filter)."""
    result = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True)
    return " ass " in result.stdout


def _escape_drawtext(text: str) -> str:
    """Escape text for use as a drawtext filter value (ffmpeg filter syntax)."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\u2019")   # curly apostrophe — avoids quote delimiter clash
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    return text


# ---------------------------------------------------------------------------
# Font detection
# ---------------------------------------------------------------------------

def _find_font() -> str:
    """
    Return the best available bold font name for libass.
    Checks fc-list first (Linux / macOS with fontconfig), then known file paths.
    Logs which font was chosen.
    """
    # Try fontconfig lookup (works on Linux and macOS with Homebrew fontconfig)
    try:
        for name in ("Helvetica Neue Bold", "Helvetica Neue", "Arial Bold", "Arial"):
            result = subprocess.run(
                ["fc-list", f":family={name}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info("Caption font: %s (found via fc-list)", name)
                return name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fall back to checking known file paths
    for name, path in [
        ("Helvetica Neue Bold", "/System/Library/Fonts/HelveticaNeue.ttc"),
        ("Helvetica Neue Bold", "/Library/Fonts/HelveticaNeue.ttc"),
        ("Helvetica Neue Bold", "/System/Library/Fonts/Supplemental/Helvetica Neue.ttc"),
        ("Arial Bold",          "/Library/Fonts/Arial Bold.ttf"),
        ("Arial Bold",          "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("Arial Bold",          "C:/Windows/Fonts/arialbd.ttf"),
        ("Liberation Sans Bold", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("Liberation Sans Bold", "/usr/share/fonts/liberation-sans/LiberationSans-Bold.ttf"),
    ]:
        if os.path.exists(path):
            logger.info("Caption font: %s (%s)", name, path)
            return name

    logger.warning(
        "No preferred font found on disk — using 'Arial Bold' by name "
        "(ffmpeg/libass will substitute if unavailable)"
    )
    return "Arial Bold"


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------

def _srt_time_to_secs(ts: str) -> float:
    """Parse 'HH:MM:SS,mmm' → float seconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parse_srt(srt_content: str) -> list:
    """Return list of {start, end, text} dicts from SRT content."""
    entries = []
    for block in re.split(r"\n\s*\n", srt_content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1],
        )
        if not m:
            continue
        text = " ".join(lines[2:]).strip()
        if text:
            entries.append({
                "start": _srt_time_to_secs(m.group(1)),
                "end":   _srt_time_to_secs(m.group(2)),
                "text":  text,
            })
    return entries


def _split_long_entry(entry: dict) -> list:
    """
    Split an SRT entry with more than _MAX_WORDS_PER_LINE words into
    multiple timed sub-entries, distributing duration proportionally.
    """
    words = entry["text"].split()
    if len(words) <= _MAX_WORDS_PER_LINE:
        return [entry]

    total_dur = entry["end"] - entry["start"]
    total_words = len(words)
    parts = []
    i = 0
    while i < total_words:
        chunk = words[i : i + _MAX_WORDS_PER_LINE]
        chunk_start = entry["start"] + total_dur * i / total_words
        chunk_end   = entry["start"] + total_dur * min(i + _MAX_WORDS_PER_LINE, total_words) / total_words
        parts.append({"start": chunk_start, "end": chunk_end, "text": " ".join(chunk)})
        i += _MAX_WORDS_PER_LINE
    return parts


# ---------------------------------------------------------------------------
# ASS generation
# ---------------------------------------------------------------------------

def _secs_to_ass_time(secs: float) -> str:
    """Format float seconds → 'H:MM:SS.cc' ASS timestamp."""
    h  = int(secs // 3600)
    m  = int((secs % 3600) // 60)
    s  = int(secs % 60)
    cs = int(round((secs % 1) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_to_ass(srt_content: str, video_w: int, video_h: int, font_name: str,
                vertical: bool = False) -> str:
    """
    Convert SRT content to ASS format with styled captions.

    Font size: 7% of video height.
    16:9  — bottom-center, MarginV = 9% of video height.
    9:16  — 57.5% from top (slightly below centre, above platform UI).
             Achieved with \\an5\\pos(cx, cy) override per dialogue line.
    Shadow: 2px offset, 50% transparent black.  No outline.
    """
    font_size = max(28, int(video_h * 0.07))
    margin_v  = max(20, int(video_h * 0.09))

    # ASS colour format: &HAABBGGRR  (AA: 00=opaque, FF=transparent)
    primary_colour = "&H00FFFFFF"  # white, fully opaque
    shadow_colour  = "&H80000000"  # black, 50% transparent

    entries = _parse_srt(srt_content)
    all_lines = []
    for entry in entries:
        all_lines.extend(_split_long_entry(entry))

    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "WrapStyle: 1",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # BorderStyle=1, Outline=0 (no border), Shadow=2 (2px drop), Alignment=2 (bottom-center)
        f"Style: Default,{font_name},{font_size},"
        f"{primary_colour},&H000000FF,&H00000000,{shadow_colour},"
        f"-1,0,0,0,100,100,0,0,"
        f"1,0,2,"
        f"2,10,10,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])

    if vertical:
        # \an5 = middle-center anchor; \pos(cx, cy) places it at 57.5% from top
        cx = video_w // 2
        cy = int(video_h * 0.575)
        pos_tag = f"{{\\an5\\pos({cx},{cy})}}"
        dialogue_lines = [
            f"Dialogue: 0,{_secs_to_ass_time(ln['start'])},"
            f"{_secs_to_ass_time(ln['end'])},Default,,0,0,0,,{pos_tag}{ln['text']}"
            for ln in all_lines
        ]
    else:
        dialogue_lines = [
            f"Dialogue: 0,{_secs_to_ass_time(ln['start'])},"
            f"{_secs_to_ass_time(ln['end'])},Default,,0,0,0,,{ln['text']}"
            for ln in all_lines
        ]

    return header + "\n" + "\n".join(dialogue_lines)


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

def burn_captions_task(clip_id: int):
    """
    Background task: burn styled captions into rendered clip(s).

    Operates on both the 16:9 clip (preview_path) and the 9:16 clip
    (vertical_path) if they exist.  Requires srt_path to be set.
    Saves to storage/clips/{id}_captioned.mp4 and/or
    storage/clips/{id}_vertical_captioned.mp4.
    """
    clip = get_clip_candidate(clip_id)
    if not clip:
        return

    srt_path = clip.get("srt_path")
    if not srt_path or not os.path.exists(srt_path):
        logger.error("burn_captions: no SRT file for clip_id=%s", clip_id)
        return

    with open(srt_path, encoding="utf-8") as f:
        srt_content = f.read()

    font_name = _find_font()
    updates = {}

    def _burn(source: str, output_path: str, is_vertical: bool = False) -> bool:
        w, h = get_video_dimensions(source)

        if _has_libass():
            ass_content = _srt_to_ass(srt_content, w, h, font_name, vertical=is_vertical)
            ass_tmp = None
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".ass", delete=False, mode="w", encoding="utf-8"
                ) as tmp:
                    tmp.write(ass_content)
                    ass_tmp = tmp.name
                result = subprocess.run(
                    [
                        "ffmpeg", "-i", source,
                        "-vf", f"ass={ass_tmp}",
                        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                        "-c:a", "copy",
                        "-y", output_path,
                    ],
                    capture_output=True,
                    text=True,
                )
            finally:
                if ass_tmp and os.path.exists(ass_tmp):
                    os.unlink(ass_tmp)
        else:
            logger.warning(
                "ffmpeg built without libass — using drawtext fallback. "
                "For full styled captions: brew tap homebrew-ffmpeg/ffmpeg && "
                "brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass"
            )
            entries = []
            for e in _parse_srt(srt_content):
                entries.extend(_split_long_entry(e))

            font_size = max(28, int(h * 0.07))
            margin_v  = max(20, int(h * 0.09))
            parts = []
            for e in entries:
                text = _escape_drawtext(e["text"])
                if is_vertical:
                    # 57.5% from top, text vertically centered on that line
                    y_expr = f"(h*0.575-text_h/2)"
                else:
                    y_expr = f"h-{margin_v + font_size}"
                parts.append(
                    f"drawtext=font='{font_name}':text='{text}':"
                    f"fontsize={font_size}:fontcolor=white:"
                    f"shadowcolor=black@0.5:shadowx=2:shadowy=2:"
                    f"x=(w-text_w)/2:y={y_expr}:"
                    f"enable='between(t\\,{e['start']:.3f}\\,{e['end']:.3f})'"
                )
            result = subprocess.run(
                [
                    "ffmpeg", "-i", source,
                    "-vf", ",".join(parts),
                    "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                    "-c:a", "copy",
                    "-y", output_path,
                ],
                capture_output=True,
                text=True,
            )

        if result.returncode != 0:
            logger.error(
                "ffmpeg caption burn failed for clip_id=%s (%s):\n%s",
                clip_id, output_path, result.stderr,
            )
            return False
        return True

    preview = clip.get("preview_path")
    if preview and os.path.exists(preview):
        out = os.path.join(CLIPS_DIR, f"{clip_id}_captioned.mp4")
        if _burn(preview, out, is_vertical=False):
            updates["captioned_path"] = out
            logger.info("Captions burned (16:9) for clip_id=%s", clip_id)

    vertical = clip.get("vertical_path")
    if vertical and os.path.exists(vertical):
        out = os.path.join(CLIPS_DIR, f"{clip_id}_vertical_captioned.mp4")
        if _burn(vertical, out, is_vertical=True):
            updates["vertical_captioned_path"] = out
            logger.info("Captions burned (9:16) for clip_id=%s", clip_id)

    if updates:
        update_clip_candidate(clip_id, **updates)
    else:
        logger.error("burn_captions: nothing was burned for clip_id=%s", clip_id)
