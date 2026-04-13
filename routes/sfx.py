import os
import subprocess
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config import SFX_DIR
from database import create_sfx_entry, delete_sfx_entry, get_all_sfx, get_sfx_entry

router = APIRouter()

_ALLOWED_EXTENSIONS = {".wav", ".mp3"}
_MAX_DURATION = 2.0
_VALID_CATEGORIES = {"transition", "impact", "subtle", "musical"}


def _get_audio_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


@router.post("/sfx/upload", status_code=201)
async def upload_sfx(
    file: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form("transition"),
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .wav and .mp3 files are accepted.")
    if category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of: {', '.join(sorted(_VALID_CATEGORIES))}")
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(SFX_DIR, safe_name)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    duration = _get_audio_duration(save_path)
    if duration <= 0:
        os.remove(save_path)
        raise HTTPException(status_code=400, detail="Could not determine audio duration. Is this a valid audio file?")
    if duration > _MAX_DURATION:
        os.remove(save_path)
        raise HTTPException(
            status_code=400,
            detail=f"Sound effect must be under {_MAX_DURATION}s (got {duration:.2f}s). Trim it first.",
        )

    sfx_id = create_sfx_entry(
        name=name.strip(),
        filename=safe_name,
        file_path=save_path,
        duration_seconds=round(duration, 3),
        category=category,
        is_default=False,
    )
    return get_sfx_entry(sfx_id)


@router.get("/sfx")
def list_sfx():
    return get_all_sfx()


@router.delete("/sfx/{sfx_id}", status_code=204)
def remove_sfx(sfx_id: int):
    entry = get_sfx_entry(sfx_id)
    if not entry:
        raise HTTPException(status_code=404, detail="SFX not found.")
    if entry.get("is_default"):
        raise HTTPException(status_code=400, detail="Default sound effects cannot be deleted.")
    path = entry.get("file_path")
    if path and os.path.exists(path):
        os.remove(path)
    delete_sfx_entry(sfx_id)


@router.get("/sfx/{sfx_id}/preview")
def preview_sfx(sfx_id: int):
    entry = get_sfx_entry(sfx_id)
    if not entry:
        raise HTTPException(status_code=404, detail="SFX not found.")
    path = entry.get("file_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file not found on disk.")
    media_type = "audio/mpeg" if path.endswith(".mp3") else "audio/wav"
    return FileResponse(path, media_type=media_type)
