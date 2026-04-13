import logging
import os
import subprocess

from config import CLIPS_DIR
from database import get_clip_candidate, get_media_asset, update_clip_candidate

logger = logging.getLogger(__name__)


def render_clip(clip_id: int):
    """
    Background task: cut the clip from the original MP4 using ffmpeg.
    Tries stream copy first, falls back to re-encode if that fails.
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

    start    = clip["start_sec"]
    duration = clip["end_sec"] - start
    output_path = os.path.join(CLIPS_DIR, f"{clip_id}.mp4")

    base_args = ["ffmpeg", "-ss", str(start), "-i", source, "-t", str(duration), "-y"]

    result = subprocess.run(
        base_args + ["-c", "copy", "-avoid_negative_ts", "make_zero", output_path],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.warning("Stream copy failed for clip_id=%s, falling back to re-encode", clip_id)
        result = subprocess.run(
            base_args + ["-c:v", "libx264", "-c:a", "aac", output_path],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        logger.error("ffmpeg render failed for clip_id=%s:\n%s", clip_id, result.stderr)
        update_clip_candidate(clip_id, status="error")
        return

    update_clip_candidate(clip_id, status="ready", preview_path=output_path)
    logger.info("Clip rendered: clip_id=%s -> %s", clip_id, output_path)
