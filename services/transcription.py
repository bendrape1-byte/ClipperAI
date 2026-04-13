import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time

import openai

from config import AUDIO_DIR, CHUNK_DURATION, CHUNK_SIZE_LIMIT
from database import create_transcript, update_media_asset

logger = logging.getLogger(__name__)


def _get_duration(file_path: str):
    """Return video/audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except Exception as exc:
        logger.warning("Could not read duration: %s", exc)
        return None


def _transcribe_single(client, audio_path: str, time_offset: float = 0.0):
    """Transcribe one audio file; shift all timestamps by time_offset."""
    last_exc = None
    for attempt in range(3):
        try:
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            break  # success
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            last_exc = exc
            wait = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(
                "_transcribe_single: attempt %d/3 failed (%s), retrying in %ds",
                attempt + 1, type(exc).__name__, wait,
            )
            time.sleep(wait)
    else:
        raise last_exc
    segments = [
        {
            "start": seg.start + time_offset,
            "end": seg.end + time_offset,
            "text": seg.text,
        }
        for seg in (response.segments or [])
    ]
    words = [
        {
            "word": w.word,
            "start": w.start + time_offset,
            "end": w.end + time_offset,
        }
        for w in (response.words or [])
    ]
    return response.language, segments, words


def transcribe_audio(media_id: int, audio_path: str):
    """
    Transcribe extracted audio using Whisper.
    Splits into ~10-min chunks if the file exceeds the 24 MB API limit.
    Chains automatically from extract_audio.
    """
    update_media_asset(media_id, status="transcribing")
    logger.info("Transcribing audio for media_id=%s", media_id)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set — cannot transcribe media_id=%s", media_id)
        update_media_asset(media_id, status="error")
        return

    client = openai.OpenAI(api_key=api_key)
    tmp_dir = None

    try:
        file_size = os.path.getsize(audio_path)

        if file_size <= CHUNK_SIZE_LIMIT:
            language, segments, words = _transcribe_single(client, audio_path)
        else:
            logger.info(
                "Audio is %.1f MB — splitting into %ds chunks",
                file_size / 1024 / 1024,
                CHUNK_DURATION,
            )
            tmp_dir = tempfile.mkdtemp()
            chunk_pattern = os.path.join(tmp_dir, "chunk_%03d.mp3")
            subprocess.run(
                [
                    "ffmpeg", "-i", audio_path,
                    "-f", "segment", "-segment_time", str(CHUNK_DURATION),
                    "-c", "copy", "-y", chunk_pattern,
                ],
                capture_output=True,
                check=True,
            )
            chunk_files = sorted(glob.glob(os.path.join(tmp_dir, "chunk_*.mp3")))

            language = None
            segments = []
            words = []
            for i, chunk_path in enumerate(chunk_files):
                offset = i * CHUNK_DURATION
                chunk_lang, chunk_segs, chunk_words = _transcribe_single(client, chunk_path, offset)
                if language is None:
                    language = chunk_lang
                segments.extend(chunk_segs)
                words.extend(chunk_words)
                logger.info(
                    "Transcribed chunk %d/%d for media_id=%s",
                    i + 1, len(chunk_files), media_id,
                )

        for idx, seg in enumerate(segments):
            seg["id"] = idx

        full_text = " ".join(seg["text"].strip() for seg in segments)
        create_transcript(
            media_asset_id=media_id,
            language=language or "",
            transcript_json=json.dumps(segments),
            words_json=json.dumps(words),
            full_text=full_text,
        )
        update_media_asset(media_id, status="transcribed")
        logger.info(
            "Transcription complete for media_id=%s (%d segments) — ready to analyze",
            media_id, len(segments),
        )

    except Exception as exc:
        logger.exception("Transcription failed for media_id=%s: %s", media_id, exc)
        update_media_asset(media_id, status="error")
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_audio(media_id: int, video_path: str):
    """
    Background task: extract audio from video, then chain into transcription.
    Called after upload or YouTube download completes.
    """
    update_media_asset(media_id, status="processing")
    logger.info("Extracting audio for media_id=%s", media_id)

    audio_path = os.path.join(AUDIO_DIR, f"{media_id}.mp3")

    try:
        result = subprocess.run(
            ["ffmpeg", "-i", video_path, "-vn", "-q:a", "0", "-y", audio_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("ffmpeg failed for media_id=%s:\n%s", media_id, result.stderr)
            update_media_asset(media_id, status="error")
            return

        duration = _get_duration(video_path)
        update_media_asset(media_id, audio_file_path=audio_path, duration_seconds=duration)
        logger.info("Audio extracted for media_id=%s (%.1fs)", media_id, duration or 0)

    except FileNotFoundError:
        logger.error("ffmpeg not found — is it installed and on PATH?")
        update_media_asset(media_id, status="error")
        return
    except Exception as exc:
        logger.exception("Unexpected error extracting audio for media_id=%s: %s", media_id, exc)
        update_media_asset(media_id, status="error")
        return

    transcribe_audio(media_id, audio_path)
