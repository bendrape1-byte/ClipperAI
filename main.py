import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import ORIGINALS_DIR, AUDIO_DIR, CLIPS_DIR
from database import init_db
from routes.clips import router as clips_router
from routes.media import router as media_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for directory in (ORIGINALS_DIR, AUDIO_DIR, CLIPS_DIR):
        os.makedirs(directory, exist_ok=True)
    init_db()
    logger.info("Clip Engine ready.")
    yield


app = FastAPI(title="Clip Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(media_router, prefix="/api")
app.include_router(clips_router, prefix="/api")

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
