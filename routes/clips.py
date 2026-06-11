import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_clip_candidate, update_clip_candidate
from services.rendering import render_clip

router = APIRouter()


class ExtendRequest(BaseModel):
    start_delta: float = 0.0
    end_delta: float = 0.0


@router.post("/clips/{clip_id}/render", status_code=202)
def render_clip_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    if not get_clip_candidate(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    background_tasks.add_task(render_clip, clip_id)
    return {"id": clip_id, "status": "rendering"}


@router.post("/clips/{clip_id}/extend", status_code=202)
def extend_clip(clip_id: int, body: ExtendRequest, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    new_start = max(0.0, clip["start_sec"] + body.start_delta)
    new_end   = clip["end_sec"] + body.end_delta
    if new_end <= new_start:
        raise HTTPException(status_code=400, detail="end_sec must be greater than start_sec.")
    update_clip_candidate(clip_id, start_sec=new_start, end_sec=new_end, status="pending", preview_path=None)
    background_tasks.add_task(render_clip, clip_id)
    return {"id": clip_id, "start_sec": new_start, "end_sec": new_end, "status": "rendering"}


@router.get("/clips/{clip_id}/download")
def download_clip(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip has not been rendered yet.")
    path = clip["preview_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Clip file missing from disk.")
    filename = f"clip_{clip_id}_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/clips/{clip_id}")
def get_clip(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    return clip


@router.post("/clips/{clip_id}/approve")
def approve_clip(clip_id: int):
    if not get_clip_candidate(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    update_clip_candidate(clip_id, status="approved")
    return {"id": clip_id, "status": "approved"}


@router.post("/clips/{clip_id}/reject")
def reject_clip(clip_id: int):
    if not get_clip_candidate(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found.")
    update_clip_candidate(clip_id, status="rejected")
    return {"id": clip_id, "status": "rejected"}
