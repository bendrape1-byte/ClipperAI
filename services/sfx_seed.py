"""
services/sfx_seed.py — Generate and seed the default SFX library on first run.

All sounds are synthesised entirely with ffmpeg (no external files, no licenses).
Seeding only runs once: if sfx_library table is non-empty, this is a no-op.
"""

import logging
import os
import subprocess

from config import SFX_DIR
from database import create_sfx_entry, sfx_library_is_empty

logger = logging.getLogger(__name__)

# Each entry: name, filename, category, is_default, nominal duration (s), ffmpeg args
_SEED = [
    {
        "name": "Soft Whoosh",
        "filename": "soft_whoosh.wav",
        "category": "transition",
        "is_default": True,
        "duration": 0.25,
        # Sine sweep 200 Hz → 800 Hz over 0.25 s
        # Phase integral: 200t + (300/0.25)t² = 200t + 1200t²
        "cmd": [
            "-f", "lavfi",
            "-i", "aevalsrc=sin(2*PI*(200*t+1200*t*t)):s=44100:d=0.25",
            "-af", "afade=t=in:d=0.03,afade=t=out:st=0.22:d=0.03",
        ],
    },
    {
        "name": "Sharp Swoosh",
        "filename": "sharp_swoosh.wav",
        "category": "transition",
        "is_default": False,
        "duration": 0.15,
        # Sine sweep 400 Hz → 2000 Hz over 0.15 s
        # Phase integral: 400t + (800/0.15)t² ≈ 400t + 5333t²
        "cmd": [
            "-f", "lavfi",
            "-i", "aevalsrc=sin(2*PI*(400*t+5333*t*t)):s=44100:d=0.15",
            "-af", "afade=t=in:d=0.01,afade=t=out:st=0.14:d=0.01",
        ],
    },
    {
        "name": "Low Thud",
        "filename": "low_thud.wav",
        "category": "impact",
        "is_default": True,
        "duration": 0.2,
        # 80 Hz sine with exponential decay (exp(-20t) → 0 by ~0.2 s)
        "cmd": [
            "-f", "lavfi",
            "-i", "aevalsrc=sin(2*PI*80*t)*exp(-20*t):s=44100:d=0.2",
            "-af", "afade=t=in:d=0.005,afade=t=out:st=0.195:d=0.005",
        ],
    },
    {
        "name": "Subtle Pop",
        "filename": "subtle_pop.wav",
        "category": "subtle",
        "is_default": True,
        "duration": 0.1,
        # White noise burst bandpassed around 2 kHz — approximated with overlapping
        # sine tones to avoid dependency on anoisesrc availability
        "cmd": [
            "-f", "lavfi",
            "-i", (
                "aevalsrc="
                "0.2*(sin(2*PI*1200*t)+sin(2*PI*1600*t)+sin(2*PI*2000*t)"
                "+sin(2*PI*2400*t)+sin(2*PI*2800*t))"
                "*exp(-30*t):s=44100:d=0.1"
            ),
            "-af", "afade=t=in:d=0.005,afade=t=out:st=0.09:d=0.01",
        ],
    },
    {
        "name": "Click",
        "filename": "click.wav",
        "category": "subtle",
        "is_default": False,
        "duration": 0.05,
        # Short damped 3 kHz tone — clean click
        "cmd": [
            "-f", "lavfi",
            "-i", "aevalsrc=sin(2*PI*3000*t)*exp(-80*t):s=44100:d=0.05",
        ],
    },
]


def seed_sfx_library():
    """Generate and insert default SFX. No-op if table already has entries."""
    if not sfx_library_is_empty():
        return
    logger.info("Seeding SFX library with %d default sounds…", len(_SEED))
    os.makedirs(SFX_DIR, exist_ok=True)
    for sfx in _SEED:
        path = os.path.join(SFX_DIR, sfx["filename"])
        cmd = ["ffmpeg"] + sfx["cmd"] + ["-y", path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("Failed to generate %s:\n%s", sfx["filename"], result.stderr)
            continue
        create_sfx_entry(
            name=sfx["name"],
            filename=sfx["filename"],
            file_path=path,
            duration_seconds=sfx["duration"],
            category=sfx["category"],
            is_default=sfx["is_default"],
        )
        logger.info("Generated SFX: %s → %s", sfx["name"], path)
