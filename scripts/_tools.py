"""Make the skill's own copies of ffmpeg and ffprobe findable. Stdlib only."""
import json
import os
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def use_local_tools():
    """Append the folders setup.py recorded to PATH. Tools already on PATH keep winning."""
    cfg = SKILL / "config.json"
    if cfg.exists():
        extra = json.loads(cfg.read_text()).get("path", [])
        os.environ["PATH"] = os.pathsep.join([os.environ.get("PATH", "")] + extra)
