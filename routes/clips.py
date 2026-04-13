import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_clip_candidate, update_clip_candidate
from services.captions import generate_srt_task
from services.production import produce_clip
from services.reframe import render_vertical_clip
from services.rendering import render_clip
from services.styled_captions import burn_captions_task

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


@router.post("/clips/{clip_id}/generate-srt", status_code=202)
def generate_srt_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before generating SRT.")
    background_tasks.add_task(generate_srt_task, clip_id)
    return {"id": clip_id, "status": "generating_srt"}


@router.get("/clips/{clip_id}/download-srt")
def download_srt(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    srt_path = clip.get("srt_path")
    if not srt_path or not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="SRT not generated yet.")
    filename = f"clip_{clip_id}_{clip.get('title', '').replace(' ', '_')[:40]}.srt"
    return FileResponse(srt_path, media_type="text/plain", filename=filename)


@router.post("/clips/{clip_id}/render-vertical", status_code=202)
def render_vertical_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before creating vertical version.")
    background_tasks.add_task(render_vertical_clip, clip_id)
    return {"id": clip_id, "vertical_status": "rendering"}


@router.get("/clips/{clip_id}/download-vertical")
def download_vertical(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    vertical_path = clip.get("vertical_path")
    if not vertical_path or not os.path.exists(vertical_path):
        raise HTTPException(status_code=404, detail="Vertical clip not generated yet.")
    filename = f"clip_{clip_id}_vertical_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
    return FileResponse(vertical_path, media_type="video/mp4", filename=filename)


@router.post("/clips/{clip_id}/burn-captions", status_code=202)
def burn_captions_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if clip.get("status") != "ready" or not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before burning captions.")
    if not clip.get("srt_path"):
        raise HTTPException(status_code=400, detail="SRT must be generated before burning captions.")
    background_tasks.add_task(burn_captions_task, clip_id)
    return {"id": clip_id, "status": "burning_captions"}


@router.get("/clips/{clip_id}/download-captioned")
def download_captioned(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("captioned_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Captioned clip not ready yet.")
    filename = f"clip_{clip_id}_captioned_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/clips/{clip_id}/download-vertical-captioned")
def download_vertical_captioned(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("vertical_captioned_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Vertical captioned clip not ready yet.")
    filename = f"clip_{clip_id}_vertical_captioned_{clip.get('title', '').replace(' ', '_')[:40]}.mp4"
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


@router.post("/clips/{clip_id}/produce", status_code=202)
def produce_clip_endpoint(clip_id: int, background_tasks: BackgroundTasks):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    if not clip.get("preview_path"):
        raise HTTPException(status_code=400, detail="Clip must be rendered before production.")
    update_clip_candidate(clip_id, production_status="producing")
    background_tasks.add_task(produce_clip, clip_id)
    return {"id": clip_id, "production_status": "producing"}


@router.get("/clips/{clip_id}/download-produced")
def download_produced(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("produced_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Produced clip not ready yet.")
    filename = f"clip_{clip_id}_produced.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)


@router.get("/clips/{clip_id}/download-vertical-produced")
def download_vertical_produced(clip_id: int):
    clip = get_clip_candidate(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found.")
    path = clip.get("vertical_produced_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Vertical produced clip not ready yet.")
    filename = f"clip_{clip_id}_vertical_produced.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)
