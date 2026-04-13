import json
import logging
import os
import subprocess
import tempfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import (
    create_clip_profile,
    get_all_profiles,
    get_clip_profile,
    get_default_sfx,
    get_sfx_entry,
    update_clip_profile,
)
from database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

_PREVIEW_W, _PREVIEW_H = 640, 360

_VALID_STYLES = {"crossfade", "dip_to_black", "wipe_left", "cut"}


# ---------------------------------------------------------------------------
# Transition preview helpers
# ---------------------------------------------------------------------------

def _find_any_rendered_clip():
    """Return path to the first clip file that exists on disk, or None."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT preview_path FROM clip_candidates WHERE preview_path IS NOT NULL"
        ).fetchall()
    for row in rows:
        p = row[0]
        if p and os.path.exists(p):
            return p
    return None


def _get_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _cleanup(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def _generate_preview(
    transition_style: str,
    sfx_path,
    clip_path,
    output_path: str,
) -> bool:
    """
    Render a 3-second preview MP4 demonstrating the chosen transition and SFX
    at the 1.5-second mark.

    Transitions use per-segment fade=out / fade=in filters joined by concat —
    no xfade, so timebase mismatches are not a problem.

    If a real clip is available it is used for both segments (A: 0–1.5 s,
    B: taken from a different offset).  If not, lavfi colour blocks are used.
    """
    from services.broll import _FADE_DUR, _SFX_LEAD

    fade_dur     = _FADE_DUR.get(transition_style, 0.15)
    use_fade     = fade_dur > 0
    sfx_lead     = _SFX_LEAD.get(transition_style, 0.05)

    seg       = 1.5          # each half is 1.5 s; total is always 3.0 s
    video_dur = seg * 2
    sfx_delay_ms = max(0, int((seg - sfx_lead) * 1000))

    W, H = _PREVIEW_W, _PREVIEW_H
    scale_pad = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )

    cmd          = ["ffmpeg"]
    has_audio    = False
    filter_parts = []
    map_args     = []

    # ------------------------------------------------------------------
    # Choose video sources
    # ------------------------------------------------------------------
    clip_dur = 0.0
    if clip_path:
        clip_dur = _get_duration(clip_path)

    use_real_clip = clip_path is not None and clip_dur >= 2.0

    if use_real_clip:
        cmd += ["-i", clip_path]

        b_start = min(max(seg + 0.5, clip_dur * 0.45), clip_dur - seg)

        filter_parts += [
            f"[0:v]trim=0:{seg:.4f},setpts=PTS-STARTPTS,{scale_pad}[av]",
            f"[0:v]trim=start={b_start:.4f}:end={b_start+seg:.4f},"
            f"setpts=PTS-STARTPTS,{scale_pad}[bv]",
        ]
        filter_parts.append(
            f"[0:a]atrim=0:{video_dur:.4f},asetpts=PTS-STARTPTS,volume=0.15[abase]"
        )
        audio_label   = "[abase]"
        has_audio     = True
        sfx_input_idx = 1

    else:
        cmd += [
            "-f", "lavfi", "-i",
            f"color=c=#0a1e3c:s={W}x{H}:r=30:d={seg + 0.5}",
            "-f", "lavfi", "-i",
            f"color=c=#0a2e1c:s={W}x{H}:r=30:d={seg + 0.5}",
        ]
        filter_parts += [
            f"[0:v]trim=0:{seg:.4f},setpts=PTS-STARTPTS,setsar=1[av]",
            f"[1:v]trim=0:{seg:.4f},setpts=PTS-STARTPTS,setsar=1[bv]",
        ]
        audio_label   = None
        sfx_input_idx = 2

    # ------------------------------------------------------------------
    # Build video transition: fade=out on A, fade=in on B, then concat
    # ------------------------------------------------------------------
    if use_fade:
        filter_parts.append(
            f"[av]fade=t=out:st={max(0.0, seg - fade_dur):.4f}:d={fade_dur:.4f}[afaded]"
        )
        filter_parts.append(
            f"[bv]fade=t=in:st=0:d={fade_dur:.4f}[bfaded]"
        )
        filter_parts.append("[afaded][bfaded]concat=n=2:v=1:a=0[vout]")
    else:
        filter_parts.append("[av][bv]concat=n=2:v=1:a=0[vout]")

    map_args += ["-map", "[vout]"]

    # ------------------------------------------------------------------
    # SFX audio
    # ------------------------------------------------------------------
    if sfx_path:
        cmd += ["-i", sfx_path]
        filter_parts.append(
            f"[{sfx_input_idx}:a]adelay={sfx_delay_ms}:all=1,volume=0.7[sfx]"
        )
        if audio_label:
            filter_parts.append(
                f"{audio_label}[sfx]amix=inputs=2:duration=first:normalize=0[aout]"
            )
        else:
            filter_parts.append("[sfx]asetpts=PTS-STARTPTS[aout]")
        map_args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
        has_audio = True
    elif has_audio:
        filter_parts = [
            p.replace("[abase]", "[aout]") if "[abase]" in p else p
            for p in filter_parts
        ]
        map_args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]

    if not has_audio:
        map_args += ["-an"]

    # ------------------------------------------------------------------
    # Assemble and run
    # ------------------------------------------------------------------
    cmd += [
        "-filter_complex", ";".join(filter_parts),
        *map_args,
        "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-t", f"{video_dur:.4f}",
        "-y", output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("preview_transition ffmpeg failed:\n%s", result.stderr)
        return False
    return True


class PreviewRequest(BaseModel):
    transition_style: str = "crossfade"
    sfx_id: Optional[int] = None


@router.post("/profiles/preview-transition")
def preview_transition(body: PreviewRequest, background_tasks: BackgroundTasks):
    """
    Generate a 3-second sample video that demonstrates the requested transition
    style and SFX, then stream it as an MP4.  The temp file is deleted after
    the response is sent.
    """
    style = body.transition_style if body.transition_style in _VALID_STYLES else "crossfade"

    # Resolve SFX path
    sfx_path = None
    if body.sfx_id:
        entry = get_sfx_entry(body.sfx_id)
        if entry and entry.get("file_path") and os.path.exists(entry["file_path"]):
            sfx_path = entry["file_path"]
    if sfx_path is None:
        entry = get_default_sfx("transition")
        if entry and entry.get("file_path") and os.path.exists(entry["file_path"]):
            sfx_path = entry["file_path"]

    clip_path = _find_any_rendered_clip()

    tmp = tempfile.mktemp(suffix=".mp4")
    ok  = _generate_preview(style, sfx_path, clip_path, tmp)

    if not ok:
        _cleanup(tmp)
        raise HTTPException(status_code=500, detail="Preview generation failed — check server logs.")

    background_tasks.add_task(_cleanup, tmp)
    return FileResponse(tmp, media_type="video/mp4", filename="preview.mp4")


class ProfileCreate(BaseModel):
    name: str
    host_name: str
    host_description: str = ""
    guest_name: str = ""
    guest_description: str = ""
    topic: str = ""
    tone: list = []
    audience: list = []
    priorities: list = []
    avoid: list = []
    additional_notes: str = ""
    transition_sfx_id: Optional[int] = None
    transition_style: str = "crossfade"


@router.post("/profiles", status_code=201)
def create_profile_route(body: ProfileCreate):
    style = body.transition_style if body.transition_style in _VALID_STYLES else "crossfade"
    profile_id = create_clip_profile(
        name=body.name,
        host_name=body.host_name,
        host_description=body.host_description or None,
        guest_name=body.guest_name or None,
        guest_description=body.guest_description or None,
        topic=body.topic or None,
        tone=body.tone,
        audience=body.audience,
        priorities=body.priorities,
        avoid=body.avoid,
        additional_notes=body.additional_notes or None,
        transition_sfx_id=body.transition_sfx_id,
        transition_style=style,
    )
    return get_clip_profile(profile_id)


@router.get("/profiles")
def list_profiles_route():
    return get_all_profiles()


@router.get("/profiles/{profile_id}")
def get_profile_route(profile_id: int):
    profile = get_clip_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return profile


@router.put("/profiles/{profile_id}")
def update_profile_route(profile_id: int, body: ProfileCreate):
    if not get_clip_profile(profile_id):
        raise HTTPException(status_code=404, detail="Profile not found.")
    style = body.transition_style if body.transition_style in _VALID_STYLES else "crossfade"
    update_clip_profile(
        profile_id,
        name=body.name,
        host_name=body.host_name,
        host_description=body.host_description or None,
        guest_name=body.guest_name or None,
        guest_description=body.guest_description or None,
        topic=body.topic or None,
        tone=json.dumps(body.tone),
        audience=json.dumps(body.audience),
        priorities=json.dumps(body.priorities),
        avoid=json.dumps(body.avoid),
        additional_notes=body.additional_notes or None,
        transition_sfx_id=body.transition_sfx_id,
        transition_style=style,
    )
    return get_clip_profile(profile_id)
