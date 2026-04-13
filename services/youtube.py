import logging
import os
import re

from config import ORIGINALS_DIR
from database import update_media_asset
from services.transcription import extract_audio

logger = logging.getLogger(__name__)

_YOUTUBE_RE = re.compile(
    r'(?:https?://)?(?:www\.)?'
    r'(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)'
    r'[\w-]+'
)


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_RE.match(url.strip()))


def download_youtube(media_id: int, url: str):
    """
    Background task: download a YouTube video via yt-dlp, then chain into audio extraction.
    Sets status to "error" on failure with a log message.
    """
    import yt_dlp

    outtmpl = os.path.join(ORIGINALS_DIR, f"{media_id}.%(ext)s")
    save_path = os.path.join(ORIGINALS_DIR, f"{media_id}.mp4")

    base_opts = {"quiet": True, "no_warnings": True}

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duration = info.get("duration")
        if duration and duration > 4 * 3600:
            update_media_asset(media_id, status="error")
            logger.error(
                "YouTube video too long (%.0f min) for media_id=%s — limit is 4 hours",
                duration / 60, media_id,
            )
            return

        title     = info.get("title") or f"youtube_{media_id}"
        thumbnail = info.get("thumbnail")
        channel   = info.get("channel") or info.get("uploader")

        update_media_asset(
            media_id,
            title=title,
            filename=title,
            thumbnail_url=thumbnail,
            channel_name=channel,
        )

        ydl_opts = {
            **base_opts,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(save_path):
            raise FileNotFoundError(f"Expected output file not found: {save_path}")

        update_media_asset(media_id, original_file_path=save_path)
        logger.info("YouTube download complete for media_id=%s: %s", media_id, title)

    except Exception as exc:
        msg = str(exc)
        if any(k in msg for k in ("403", "Forbidden", "empty", "bot", "Sign in", "cookie")):
            logger.error("YouTube blocked download for media_id=%s: %s", media_id, msg)
        else:
            logger.exception("YouTube download failed for media_id=%s: %s", media_id, exc)
        update_media_asset(media_id, status="error")
        return

    extract_audio(media_id, save_path)
