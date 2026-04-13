"""
services/reframe.py — 9:16 vertical reframing utilities.

Scene cut detection: PySceneDetect (ContentDetector)
Face tracking: OpenCV Haar cascade (haarcascade_frontalface_default.xml), sampled every 10 frames per scene
Crop strategy: one static crop X per scene segment, reset at each cut
"""

import logging
import subprocess

from config import VERTICAL_DIR
from database import get_clip_candidate, get_media_asset, update_clip_candidate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Utility functions (ffprobe / OpenCV / PySceneDetect)
# ---------------------------------------------------------------------------

def get_video_dimensions(file_path: str):
    """Return (width, height) of the first video stream."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def detect_scenes(video_path: str, total_duration: float):
    """
    Return list of (start_sec, end_sec) tuples for each scene segment.
    Falls back to a single segment covering the whole clip if no cuts are found.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector

        video = open_video(video_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=30.0))
        scene_manager.detect_scenes(video, show_progress=False)
        scenes = scene_manager.get_scene_list()

        if scenes:
            result = [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
            logger.info("Detected %d scene(s) in %s", len(result), video_path)
            return result

    except Exception as exc:
        logger.warning("Scene detection failed, using single segment: %s", exc)

    return [(0.0, total_duration)]


def get_segment_crop_x(
    video_path: str,
    start_sec: float,
    end_sec: float,
    source_w: int,
    source_h: int,
    crop_w: int,
) -> int:
    """
    Sample frames from a scene segment every 10 frames using OpenCV Haar cascade face detection.
    Returns the crop X position (left edge) centered on the average face position.
    Falls back to center crop if no face is detected.
    """
    try:
        import cv2

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        start_frame = int(start_sec * fps)
        end_frame   = max(start_frame + 1, int(end_sec * fps))
        sample_interval = 10

        face_x_positions = []

        frame_nums = list(range(start_frame, end_frame, sample_interval))
        if not frame_nums:
            frame_nums = [start_frame]

        for frame_num in frame_nums:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                break
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                face_x_positions.append(x + w / 2)

        cap.release()

        if face_x_positions:
            avg_x = sum(face_x_positions) / len(face_x_positions)
            logger.debug(
                "Segment %.1f–%.1fs: face tracked, avg_x=%.0f (%d samples)",
                start_sec, end_sec, avg_x, len(face_x_positions),
            )
        else:
            avg_x = source_w / 2
            logger.debug(
                "Segment %.1f–%.1fs: no face detected, center fallback x=%.0f",
                start_sec, end_sec, avg_x,
            )

    except Exception as exc:
        logger.warning("Face detection error, using center crop: %s", exc)
        avg_x = source_w / 2

    crop_x = int(avg_x - crop_w / 2)
    crop_x = max(0, min(crop_x, source_w - crop_w))
    return crop_x


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

def render_vertical_clip(clip_id: int):
    """
    Background task: re-render a clip as 9:16 vertical video.
    Requires the clip to already be rendered (preview_path must exist).
    Uses scene-cut detection + per-scene face tracking for crop position.
    """
    import os
    import subprocess

    update_clip_candidate(clip_id, vertical_status="rendering")

    clip = get_clip_candidate(clip_id)
    if not clip:
        logger.error("render_vertical_clip: clip_id=%s not found", clip_id)
        return

    source = clip.get("preview_path")
    if not source or not os.path.exists(source):
        logger.error("render_vertical_clip: clip must be rendered first (clip_id=%s)", clip_id)
        update_clip_candidate(clip_id, vertical_status="error")
        return

    try:
        source_w, source_h = get_video_dimensions(source)
        crop_w = int(source_h * 9 / 16)
        if crop_w > source_w:
            crop_w = source_w

        total_duration = clip["end_sec"] - clip["start_sec"]
        scenes = detect_scenes(source, total_duration)

        scene_crops = [
            (s, e, get_segment_crop_x(source, s, e, source_w, source_h, crop_w))
            for s, e in scenes
        ]

        output_path = os.path.join(VERTICAL_DIR, f"{clip_id}.mp4")

        if len(scene_crops) == 1:
            _, _, crop_x = scene_crops[0]
            result = subprocess.run(
                [
                    "ffmpeg", "-i", source,
                    "-vf", f"crop={crop_w}:{source_h}:{crop_x}:0,scale=1080:1920:flags=lanczos",
                    "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k",
                    "-y", output_path,
                ],
                capture_output=True,
                text=True,
            )
        else:
            filter_parts = []
            concat_inputs = []
            for i, (start_s, end_s, crop_x) in enumerate(scene_crops):
                filter_parts.append(
                    f"[0:v]trim=start={start_s}:end={end_s},"
                    f"crop={crop_w}:{source_h}:{crop_x}:0,"
                    f"scale=1080:1920:flags=lanczos,setpts=PTS-STARTPTS[v{i}]"
                )
                filter_parts.append(
                    f"[0:a]atrim=start={start_s}:end={end_s},asetpts=PTS-STARTPTS[a{i}]"
                )
                concat_inputs.append(f"[v{i}][a{i}]")
            n = len(scene_crops)
            filter_parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=1[vout][aout]")
            result = subprocess.run(
                [
                    "ffmpeg", "-i", source,
                    "-filter_complex", ";".join(filter_parts),
                    "-map", "[vout]", "-map", "[aout]",
                    "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k",
                    "-y", output_path,
                ],
                capture_output=True,
                text=True,
            )

        if result.returncode != 0:
            logger.error("ffmpeg vertical render failed for clip_id=%s:\n%s", clip_id, result.stderr)
            update_clip_candidate(clip_id, vertical_status="error")
            return

        update_clip_candidate(clip_id, vertical_path=output_path, vertical_status="ready")
        logger.info("Vertical clip rendered: clip_id=%s -> %s", clip_id, output_path)

    except Exception as exc:
        logger.exception("render_vertical_clip failed for clip_id=%s: %s", clip_id, exc)
        update_clip_candidate(clip_id, vertical_status="error")
