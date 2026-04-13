import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import (
    get_broll_suggestion,
    get_broll_suggestions_for_clip,
    get_clip_candidate,
    update_broll_suggestion,
)
from services.broll import composite_broll, suggest_broll, swap_broll

router = APIRouter()


class SwapRequest(BaseModel):
    search_query: str


# ---------------------------------------------------------------------------
# Clip-level endpoints
# ---------------------------------------------------------------------------

@router.post("/clips/{clip_id}/suggest-broll", status_code=202)
def suggest_broll_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before suggesting B-roll.")
    background_tasks.add_task(suggest_broll, clip_id)
    return {"id": clip_id, "status": "suggesting"}


@router.get("/clips/{clip_id}/broll")
def get_broll_endpoint(clip_id: int):
    if not get_clip_candidate(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    return get_broll_suggestions_for_clip(clip_id)


@router.post("/clips/{clip_id}/composite-broll", status_code=202)
def composite_broll_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before compositing B-roll.")
    from database import get_approved_broll_for_clip
    if not get_approved_broll_for_clip(clip_id):
        raise HTTPException(status_code=400, detail="Approve at least one B-roll suggestion first.")
    background_tasks.add_task(composite_broll, clip_id)
    return {"id": clip_id, "status": "compositing"}


@router.get("/clips/{clip_id}/download-broll")
def download_broll(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("broll_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="B-roll composite not ready yet.")
    filename = f"clip_{clip_id}_broll_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/clips/{clip_id}/download-vertical-broll")
def download_vertical_broll(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("vertical_broll_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Vertical B-roll composite not ready yet.")
    filename = f"clip_{clip_id}_vertical_broll_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


# ---------------------------------------------------------------------------
# Suggestion-level endpoints
# ---------------------------------------------------------------------------

@router.post("/broll/{suggestion_id}/approve")
def approve_broll(suggestion_id: int):
    if not get_broll_suggestion(suggestion_id):
        raise HTTPException(status_code=404, detail="B-roll suggestion not found.")
    update_broll_suggestion(suggestion_id, status="approved")
    return get_broll_suggestion(suggestion_id)


@router.post("/broll/{suggestion_id}/reject")
def reject_broll(suggestion_id: int):
    if not get_broll_suggestion(suggestion_id):
        raise HTTPException(status_code=404, detail="B-roll suggestion not found.")
    update_broll_suggestion(suggestion_id, status="rejected")
    return get_broll_suggestion(suggestion_id)


@router.post("/broll/{suggestion_id}/swap")
def swap_broll_endpoint(suggestion_id: int, body: SwapRequest):
    """Replace the Pexels clip with a new search query. Synchronous — downloads the new clip."""
    if not get_broll_suggestion(suggestion_id):
        raise HTTPException(status_code=404, detail="B-roll suggestion not found.")
    try:
        updated = swap_broll(suggestion_id, body.search_query.strip())
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        # Pexels rate limit
        raise HTTPException(status_code=429, detail=str(exc))
