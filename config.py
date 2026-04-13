import os

STORAGE_DIR = "./storage"
ORIGINALS_DIR = os.path.join(STORAGE_DIR, "originals")
AUDIO_DIR     = os.path.join(STORAGE_DIR, "audio")
CLIPS_DIR     = os.path.join(STORAGE_DIR, "clips")
CAPTIONS_DIR  = os.path.join(STORAGE_DIR, "captions")
VERTICAL_DIR  = os.path.join(STORAGE_DIR, "vertical")
BROLL_DIR     = os.path.join(STORAGE_DIR, "broll")
SFX_DIR       = os.path.join(STORAGE_DIR, "sfx")

CHUNK_SIZE_LIMIT = 24 * 1024 * 1024  # 24 MB — Whisper API hard limit
CHUNK_DURATION   = 600               # 10 minutes per chunk

WINDOW_SIZE    = 900   # 15-minute analysis windows (seconds)
WINDOW_OVERLAP = 120   # 2-minute overlap between windows
