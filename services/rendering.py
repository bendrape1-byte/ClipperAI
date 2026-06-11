import logging
import os
import subprocess
from typing import Optional

from config import CLIPS_DIR
from database import get_clip_candidate, get_media_asset, update_clip_candidate

logger = logging.getLogger(__name__)

AUDIO_FADE_SEC = 0.01  # ~10ms fade at each edge to kill the click at the cut points


def _probe_fps(source: str) -> Optional[float]:
    """Source video fps via ffprobe r_frame_rate (e.g. '30000/1001'), or None."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", source],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    raw = result.stdout.strip().splitlines()[0]
    try:
        num, _, den = raw.partition("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return fps if fps > 0 else None


def render_clip(clip_id: int):
    """
    Background task: cut the clip from the original MP4 with a frame-accurate
    re-encode. Input-seek + libx264 lands on the requested frame; stream copy
    would snap to the nearest keyframe and drift off the requested time.
    """
    update_clip_candidate(clip_id, status="rendering")

    clip = get_clip_candidate(clip_id)
    if not clip:
        logger.error("render_clip: clip_id=%s not found", clip_id)
        return

    asset = get_media_asset(clip["media_asset_id"])
    if not asset:
        logger.error("render_clip: media asset not found for clip_id=%s", clip_id)
        update_clip_candidate(clip_id, status="error")
        return

    source = asset["original_file_path"]
    if not os.path.exists(source):
        logger.error("render_clip: source file missing: %s", source)
        update_clip_candidate(clip_id, status="error")
        return

    start = clip["start_sec"]
    end   = clip["end_sec"]

    fps = _probe_fps(source)
    if fps:
        start = round(start * fps) / fps
        end   = round(end * fps) / fps
    else:
        logger.warning("render_clip: could not probe fps for %s — cutting without frame rounding", source)

    duration = end - start
    if duration <= 0:
        logger.error("render_clip: non-positive duration for clip_id=%s (%.3f)", clip_id, duration)
        update_clip_candidate(clip_id, status="error")
        return

    output_path = os.path.join(CLIPS_DIR, f"{clip_id}.mp4")
    fade_out_start = max(0.0, duration - AUDIO_FADE_SEC)

    result = subprocess.run(
        [
            "ffmpeg",
            "-ss", f"{start:.6f}",
            "-i", source,
            "-t", f"{duration:.6f}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac",
            "-af", f"afade=t=in:st=0:d={AUDIO_FADE_SEC},afade=t=out:st={fade_out_start:.6f}:d={AUDIO_FADE_SEC}",
            "-y", output_path,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("ffmpeg render failed for clip_id=%s:\n%s", clip_id, result.stderr)
        update_clip_candidate(clip_id, status="error")
        return

    update_clip_candidate(clip_id, status="ready", preview_path=output_path)
    logger.info("Clip rendered: clip_id=%s -> %s", clip_id, output_path)
