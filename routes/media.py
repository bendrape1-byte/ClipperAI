import io
import json
import os
import uuid
import zipfile

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import ORIGINALS_DIR
from database import (
    create_media_asset,
    get_clips_by_media_id,
    get_media_asset,
    get_transcript_by_media_id,
)
from services.analysis import analyze_media
from services.rendering import render_clip
from services.transcription import extract_audio
from services.youtube import download_youtube, is_youtube_url

router = APIRouter()


class YoutubeRequest(BaseModel):
    url: str


class AnalyzeRequest(BaseModel):
    context: str = ""


@router.post("/media/upload", status_code=201)
async def upload_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only .mp4 files are accepted.")

    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    save_path = os.path.join(ORIGINALS_DIR, safe_name)

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(await file.read())

    media_id = create_media_asset(filename=file.filename, original_file_path=save_path)
    background_tasks.add_task(extract_audio, media_id, save_path)

    return {"id": media_id, "filename": file.filename, "status": "uploaded"}


@router.post("/media/youtube", status_code=201)
def youtube_ingest(body: YoutubeRequest, background_tasks: BackgroundTasks):
    if not is_youtube_url(body.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")
    media_id = create_media_asset(
        filename=body.url,
        original_file_path="",
        status="downloading",
        source_type="youtube",
        source_url=body.url,
    )
    background_tasks.add_task(download_youtube, media_id, body.url)
    return {"id": media_id, "status": "downloading"}


@router.get("/media/{media_id}")
def get_media(media_id: int):
    asset = get_media_asset(media_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found.")
    return asset


@router.get("/media/{media_id}/status")
def get_media_status(media_id: int):
    asset = get_media_asset(media_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found.")
    return {"id": media_id, "status": asset["status"]}


@router.get("/media/{media_id}/transcript")
def get_transcript(media_id: int):
    if not get_media_asset(media_id):
        raise HTTPException(status_code=404, detail="Media not found.")
    transcript = get_transcript_by_media_id(media_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not available yet.")
    return {
        "id": transcript["id"],
        "media_asset_id": transcript["media_asset_id"],
        "language": transcript["language"],
        "full_text": transcript["full_text"],
        "segments": json.loads(transcript["transcript_json"] or "[]"),
        "created_at": transcript["created_at"],
    }


@router.post("/media/{media_id}/analyze", status_code=202)
def trigger_analysis(
    media_id: int,
    background_tasks: BackgroundTasks,
    body: AnalyzeRequest = Body(default_factory=AnalyzeRequest),
):
    asset = get_media_asset(media_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Media not found.")
    if not get_transcript_by_media_id(media_id):
        raise HTTPException(
            status_code=400,
            detail="No transcript yet — transcription must complete first.",
        )
    background_tasks.add_task(analyze_media, media_id, body.context)
    return {"id": media_id, "status": "analyzing"}


@router.get("/media/{media_id}/clips")
def get_clips(media_id: int):
    if not get_media_asset(media_id):
        raise HTTPException(status_code=404, detail="Media not found.")
    clips = get_clips_by_media_id(media_id)
    for c in clips:
        c["render_status"] = "ready" if c.get("preview_path") else "pending"
    clips.sort(key=lambda c: (0 if c["render_status"] == "ready" else 1, -c.get("score", 0)))
    return {"media_asset_id": media_id, "count": len(clips), "clips": clips}


@router.post("/media/{media_id}/render-all", status_code=202)
def render_all(media_id: int, background_tasks: BackgroundTasks):
    if not get_media_asset(media_id):
        raise HTTPException(status_code=404, detail="Media not found.")
    clips = get_clips_by_media_id(media_id)
    if not clips:
        raise HTTPException(status_code=404, detail="No clip candidates found.")
    for clip in clips:
        background_tasks.add_task(render_clip, clip["id"])
    return {"media_asset_id": media_id, "queued": len(clips)}


@router.get("/media/{media_id}/download-approved")
def download_approved(media_id: int):
    if not get_media_asset(media_id):
        raise HTTPException(status_code=404, detail="Media not found.")
    clips = get_clips_by_media_id(media_id)
    approved = [c for c in clips if c.get("status") == "approved"]
    if not approved:
        raise HTTPException(status_code=404, detail="No approved clips found.")

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for clip in approved:
            path = clip.get("preview_path")
            if path and os.path.exists(path):
                safe_title = (clip.get("title") or f"clip_{clip['id']}").replace(" ", "_")[:40]
                zf.write(path, f"{safe_title}_{clip['id']}.mp4")
                added += 1

    if added == 0:
        raise HTTPException(status_code=404, detail="No clip files found on disk.")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=approved_clips.zip"},
    )
