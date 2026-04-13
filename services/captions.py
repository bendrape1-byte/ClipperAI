import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

import requests

from database import get_clip_candidate, get_transcript_by_media_id, update_clip_candidate
from config import CAPTIONS_DIR

logger = logging.getLogger(__name__)

_SENTENCE_ENDS = {'.', '!', '?'}
_MIN_DURATION = 3 / 30.0   # 3 frames at 30 fps — a word held this long stands alone

_SPLIT_OVERRIDES = {
    "Beispielsweise":     ["Beispiels-", "weise"],
    "Tatverdächtiger":    ["Tat-", "verdächtiger"],
    "Tatverdächtigten":   ["Tat-", "verdächtigten"],
    "Tatverdächtigte":    ["Tat-", "verdächtigte"],
    "Menschenleben":      ["Menschen-", "leben"],
    "Abschiebungen":      ["Ab-", "schiebungen"],
}

_LANG_MAP = {
    "english": "en", "german": "de", "french": "fr", "spanish": "es",
    "italian": "it", "portuguese": "pt", "dutch": "nl", "polish": "pl",
    "russian": "ru", "japanese": "ja", "chinese": "zh", "korean": "ko",
}


def _srt_timestamp(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = int(seconds) // 60 % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _quantize(seconds: float, fps: float = 30.0) -> float:
    return round(seconds * fps) / fps


def _split_word(word: str) -> list:
    if word in _SPLIT_OVERRIDES:
        return _SPLIT_OVERRIDES[word]
    if "-" in word:
        idx = word.index("-")
        return [word[:idx + 1], word[idx + 1:]]
    return [word]


def _create_mini_audio(video_path: str, out_path: str):
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "64k", "-y", out_path],
        capture_output=True,
        check=True,
    )


def _audio_end_after_speech(audio_path: str, last_word_end: float) -> float:
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_path,
             "-af", "silencedetect=noise=-40dB:duration=0.05",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in result.stderr.splitlines():
            if "silence_start:" in line:
                t = float(line.split("silence_start:")[1].split()[0])
                if t > last_word_end:
                    return t
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return last_word_end + 0.5


def _generate_srt_content(video_path: str, language: str = "en",
                           max_chars: Optional[int] = 14) -> str:
    """
    Generate SRT content from a video file using Deepgram word-level transcription.
    Requires DEEPGRAM_API_KEY environment variable.
    """
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY environment variable is not set.")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _create_mini_audio(video_path, tmp_path)
        with open(tmp_path, "rb") as f:
            audio_data = f.read()
        resp = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={"Authorization": f"Token {api_key}", "Content-Type": "audio/mp3"},
            params={"model": "nova-2", "punctuate": "true", "words": "true", "language": language},
            data=audio_data,
            timeout=120,
        )
        resp.raise_for_status()
        alt   = resp.json()["results"]["channels"][0]["alternatives"][0]
        words = alt["words"]
        # Deepgram applies capitalisation (German nouns etc.) to the transcript
        # string but NOT to the individual word tokens in the words array.
        # Build a list of punctuation-stripped transcript tokens so we can
        # recover the correctly-cased form for each word position.
        _transcript_tokens = [
            re.sub(r'[^\w\säöüÄÖÜß\-]', '', tok)
            for tok in alt.get("transcript", "").split()
        ]
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not words:
        return ""

    expanded = []
    for idx, w in enumerate(words):
        # Use the transcript token's capitalisation when it matches the word
        # (same letters, different case).  Fall back to the raw word token if
        # the counts are off or the strings diverge (e.g. multi-token merges).
        raw = w["word"]
        if idx < len(_transcript_tokens):
            tok = _transcript_tokens[idx]
            if tok.lower() == raw.lower():
                raw = tok
        clean = re.sub(r'[^\w\säöüÄÖÜß\-]', '', raw).strip()
        if not clean:
            continue
        parts = _split_word(clean)
        if len(parts) == 1:
            expanded.append({"word": clean, "start": w["start"], "end": w["end"]})
        else:
            total = sum(len(p) for p in parts)
            span = w["end"] - w["start"]
            t = w["start"]
            for p in parts:
                dur = span * len(p) / total if total else span / len(parts)
                expanded.append({"word": p, "start": t, "end": t + dur})
                t += dur

    if not expanded:
        return ""

    chunks = []
    i = 0
    while i < len(expanded):
        w1 = expanded[i]
        ends_sentence = any(w1["word"].endswith(c) for c in _SENTENCE_ENDS)
        w1_duration   = w1["end"] - w1["start"]
        w1_long       = bool(max_chars and len(w1["word"]) > max_chars)

        # Flush w1 alone if it ends a sentence, is too long on its own,
        # or was held long enough to stand on its own (AutoCaptions min_duration rule)
        if ends_sentence or w1_long or w1_duration >= _MIN_DURATION:
            chunks.append({"text": w1["word"], "start": w1["start"], "end": w1["end"]})
            i += 1
            continue

        # w1 is short — try to pair it with the next word
        if i + 1 < len(expanded):
            w2 = expanded[i + 1]
            combined  = w1["word"] + " " + w2["word"]
            w2_long   = bool(max_chars and len(w2["word"]) > max_chars)
            over_limit = bool(max_chars and len(combined) > max_chars)
            if over_limit or w2_long:
                # Pair would exceed the char limit — flush w1 alone
                chunks.append({"text": w1["word"], "start": w1["start"], "end": w1["end"]})
                i += 1
            else:
                chunks.append({"text": combined, "start": w1["start"], "end": w2["end"]})
                i += 2
        else:
            # Last word with nothing to pair with
            chunks.append({"text": w1["word"], "start": w1["start"], "end": w1["end"]})
            i += 1

    if not chunks:
        return ""

    audio_end = _audio_end_after_speech(video_path, expanded[-1]["end"])

    lines = []
    for idx, chunk in enumerate(chunks):
        start = _quantize(chunk["start"])
        end = _quantize(chunks[idx + 1]["start"]) if idx + 1 < len(chunks) else _quantize(audio_end)
        if not chunk["text"].strip():
            continue
        lines += [str(idx + 1), f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}", chunk["text"], ""]

    return "\n".join(lines)


def generate_srt_task(clip_id: int):
    """Background task: generate an SRT file for a rendered clip using Deepgram."""
    clip = get_clip_candidate(clip_id)
    if not clip:
        return
    video_path = clip.get("preview_path")
    if not video_path or not os.path.exists(video_path):
        logger.error("generate_srt: video file missing for clip_id=%s", clip_id)
        return

    language = "en"
    transcript = get_transcript_by_media_id(clip["media_asset_id"])
    if transcript and transcript.get("language"):
        raw = transcript["language"].lower().strip()
        language = _LANG_MAP.get(raw, raw)

    try:
        srt_content = _generate_srt_content(video_path, language=language)
        if not srt_content.strip():
            logger.warning("generate_srt: empty output for clip_id=%s", clip_id)
            return
        srt_path = os.path.join(CAPTIONS_DIR, f"{clip_id}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        update_clip_candidate(clip_id, srt_path=srt_path)
        logger.info("SRT generated for clip_id=%s -> %s", clip_id, srt_path)
    except Exception as exc:
        logger.exception("SRT generation failed for clip_id=%s: %s", clip_id, exc)
