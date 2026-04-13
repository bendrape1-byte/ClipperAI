"""
services/production.py — Tier 2 production pipeline.

produce_clip() runs in sequence:
  1. Burn styled captions onto 16:9 and 9:16 renders
  2. Ask Claude + Pexels for B-roll suggestions (suggest_broll)
  3. Auto-approve every suggestion
  4. Composite B-roll + whoosh SFX onto the captioned versions
  5. Write produced_path / vertical_produced_path, set production_status='ready'

If captions fail (no SRT), the raw renders are used as composite sources.
If B-roll yields nothing, the captioned (or raw) files become the produced output.
If any step raises, production_status is set to 'error'.
"""

import logging
import os

from config import CLIPS_DIR
from database import (
    get_approved_broll_for_clip,
    get_broll_suggestions_for_clip,
    get_clip_candidate,
    update_broll_suggestion,
    update_clip_candidate,
)
from services.broll import _run_composite, suggest_broll
from services.styled_captions import burn_captions_task

logger = logging.getLogger(__name__)


def produce_clip(clip_id: int):
    """
    Background task: run the full Tier 2 production chain for one clip.
    Sets production_status = 'producing' before starting (done by the route handler),
    then 'ready' on success or 'error' on failure.
    """
    step = "init"
    try:
        clip = get_clip_candidate(clip_id)
        if not clip:
            raise RuntimeError("Clip not found")

        if not clip.get("preview_path") or not os.path.exists(clip["preview_path"]):
            raise RuntimeError("No rendered 16:9 source — run Tier 1 first")

        def _set_step(s: str):
            nonlocal step
            step = s
            update_clip_candidate(clip_id, production_step=s)

        # ── Step 1: Burn captions ───────────────────────────────────────────
        _set_step("burn_captions")
        if clip.get("srt_path") and os.path.exists(clip["srt_path"]):
            burn_captions_task(clip_id)
            clip = get_clip_candidate(clip_id)  # refresh paths
        else:
            logger.warning("produce_clip: no SRT for clip_id=%s — skipping captions", clip_id)

        # Source for compositing: prefer captioned, fall back to raw
        src_16 = clip.get("captioned_path") or clip.get("preview_path")
        src_9  = clip.get("vertical_captioned_path") or clip.get("vertical_path")

        if not src_16 or not os.path.exists(src_16):
            raise RuntimeError(f"16:9 source missing: {src_16}")

        # ── Step 2: Suggest B-roll ──────────────────────────────────────────
        _set_step("suggest_broll")
        suggest_broll(clip_id)

        # ── Step 3: Auto-approve all suggestions ───────────────────────────
        _set_step("approve_broll")
        for s in get_broll_suggestions_for_clip(clip_id):
            update_broll_suggestion(s["id"], status="approved")

        approved = get_approved_broll_for_clip(clip_id)
        valid    = [s for s in approved
                    if s.get("broll_file_path") and os.path.exists(s["broll_file_path"])]

        updates = {"production_status": "ready", "production_step": None}

        if valid:
            # ── Step 4: Composite 16:9 ─────────────────────────────────────
            _set_step("composite_16")
            out_16 = os.path.join(CLIPS_DIR, f"{clip_id}_produced.mp4")
            if _run_composite(src_16, valid, out_16):
                updates["produced_path"] = out_16
                logger.info("produce_clip: 16:9 composite done for clip_id=%s", clip_id)
            else:
                logger.warning("produce_clip: 16:9 composite failed, using captioned source")

            # ── Step 5: Composite 9:16 ─────────────────────────────────────
            if src_9 and os.path.exists(src_9):
                _set_step("composite_9")
                out_9 = os.path.join(CLIPS_DIR, f"{clip_id}_vertical_produced.mp4")
                if _run_composite(src_9, valid, out_9):
                    updates["vertical_produced_path"] = out_9
                    logger.info("produce_clip: 9:16 composite done for clip_id=%s", clip_id)

        # If composite produced nothing, fall back to captioned/raw
        if "produced_path" not in updates:
            updates["produced_path"] = src_16
        if "vertical_produced_path" not in updates and src_9 and os.path.exists(src_9):
            updates["vertical_produced_path"] = src_9

        update_clip_candidate(clip_id, **updates)
        logger.info("produce_clip: complete for clip_id=%s", clip_id)

    except Exception as exc:
        logger.exception(
            "produce_clip failed at step=%s for clip_id=%s: %s", step, clip_id, exc
        )
        update_clip_candidate(clip_id, production_status="error")
