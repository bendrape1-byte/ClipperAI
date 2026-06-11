import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import anthropic

from config import WINDOW_SIZE, WINDOW_OVERLAP
from database import (
    create_clip_candidate,
    delete_clips_by_media_id,
    get_clips_by_media_id,
    get_transcript_by_media_id,
    increment_clips_rendered,
    update_media_asset,
)

logger = logging.getLogger(__name__)

SOCIAL_MEDIA_SYSTEM_PROMPT = """You are an expert short-form video strategist and editor. You identify moments in podcast transcripts that will perform as standalone clips on Instagram Reels, TikTok, and YouTube Shorts.

HOOKS — the first 3 seconds determine whether someone scrolls past:
Strong hooks: bold contrarian claim ("most people are wrong about X"), specific surprising number, curiosity gap ("what nobody tells you about X"), story open-loop ("the day I almost lost everything"), direct value promise ("in 60 seconds here's exactly how to X")
Weak hooks: "So today I want to talk about...", "That's a really great question", "You know, I think...", "It's interesting because...", anything that requires prior context to understand

WHAT PERFORMS ON SHORT-FORM:
- Contrarian or counter-intuitive takes that challenge conventional wisdom
- Specific concrete results with numbers ("went from 0 to $10k in 47 days")
- Genuine emotion: frustration, revelation, laughter — not performed enthusiasm
- Clear insight moments where something clicks ("oh, so THAT'S why...")
- List formats with a strong opener ("3 things that will kill your startup")
- Vulnerability paired with a hard-won lesson
- Bold, confident statements without hedging or over-qualifying
- Stories with a clear arc: setup → tension → resolution, all within the clip

WHAT KILLS RETENTION:
- Starting mid-thought or referencing anything said earlier in the conversation
- Over-qualifying every claim: "it depends", "kind of", "maybe", "I guess", "sort of"
- More than 2 seconds without new information or forward momentum
- Trailing endings — the clip must land on something, not just stop
- Clips where you need to know the speaker to understand why the insight matters
- Academic or jargon-heavy language without immediate plain-language translation

SCORING GUIDE:
9-10: Exceptional hook + self-contained + strong landing + would stop a scroll cold
7-8: Strong hook, clear value, minor issues with pacing or landing
5-6: Decent content but weak hook or requires slight context
3-4: Interesting topic but poor clip boundaries or requires too much setup
1-2: Would not perform — ignore these

IDEAL STRUCTURE: Hook (0–3s grabs attention) → delivers on the hook's promise with specifics → lands on a strong final statement
SWEET SPOT: 35–65 seconds. Under 30s only if the insight is razor-sharp. Over 75s needs exceptional narrative momentum to hold."""

def _format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _build_windows(segments: list, words: list = None):
    """Split segments into overlapping 15-minute windows with word data per window."""
    if not segments:
        return []
    words = words or []
    windows = []
    total = segments[-1]["end"]
    step = WINDOW_SIZE - WINDOW_OVERLAP
    start = 0.0
    while start < total:
        end = start + WINDOW_SIZE
        window_segs = [s for s in segments if s["start"] >= start and s["start"] < end]
        if window_segs:
            window_words = [w for w in words if w["start"] >= start and w["start"] < end]
            windows.append({"start": start, "end": end, "segments": window_segs, "words": window_words})
        start += step
    return windows


def _extract_excerpt(segments: list, start_sec: float, end_sec: float) -> str:
    texts = [
        s["text"].strip()
        for s in segments
        if s["start"] >= start_sec and s["end"] <= end_sec + 2
    ]
    excerpt = " ".join(texts)
    return excerpt[:500] if len(excerpt) > 500 else excerpt


def _clean_word(w: str) -> str:
    return w.lower().strip('.,!?":;\'- ')


def _find_word_start_for_hook(words: list, hook: str) -> Optional[float]:
    """
    Find the precise start time of the hook's first word using word-level timestamps.
    Scans for the best consecutive run matching the opening of the hook.
    """
    if not words or not hook:
        return None
    hook_words = [_clean_word(w) for w in hook.split() if w.strip()]
    if not hook_words:
        return None
    best_start = None
    best_score = 0
    for i, w in enumerate(words):
        wt = _clean_word(w["word"])
        if not wt or not (wt == hook_words[0] or hook_words[0] in wt or wt in hook_words[0]):
            continue
        score = 1
        for j in range(1, min(6, len(hook_words))):
            if i + j < len(words):
                wt2 = _clean_word(words[i + j]["word"])
                hw = hook_words[j]
                if hw == wt2 or hw in wt2 or wt2 in hw:
                    score += 1
        if score > best_score:
            best_score = score
            best_start = w["start"]
    return best_start if best_score >= 2 else None


def _find_segment_for_hook(segments: list, hook: str) -> Optional[float]:
    """Fallback: segment-level word overlap match."""
    hook_words = set(hook.lower().split())
    if not hook_words:
        return None
    best_score = 0
    best_start = None
    for seg in segments:
        seg_words = set(seg["text"].lower().split())
        score = len(hook_words & seg_words)
        if score > best_score:
            best_score = score
            best_start = seg["start"]
    return best_start if best_score >= 3 else None


def _analyze_window(client, window: dict, context: str = "") -> list:
    """Send one transcript window to Claude and return clip candidates."""
    lines = [
        f"[{_format_timestamp(s['start'])}] {s['text'].strip()}"
        for s in window["segments"]
    ]
    transcript_text = "\n".join(lines)
    window_start = _format_timestamp(window["start"])
    window_end = _format_timestamp(window["end"])

    context_block = (
        f"PODCAST CONTEXT (use this to inform scoring and relevance):\n{context.strip()}\n\n"
        if context.strip() else ""
    )

    prompt = f"""{context_block}Transcript window ({window_start} – {window_end}):
{transcript_text}

Find the 3-6 best clip candidates from this window. Be selective — only include genuinely strong moments. Apply the scoring guide strictly.

Return ONLY a valid JSON array, no other text, no markdown:
[
  {{
    "start_sec": <float — exact second from transcript timestamps>,
    "end_sec": <float>,
    "title": "<5-8 word descriptive title>",
    "hook": "<the exact opening sentence of this clip>",
    "reasoning": "<one sentence: why this works as a standalone clip>",
    "score": <integer 1-10>
  }}
]"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SOCIAL_MEDIA_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()

    try:
        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            return []
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            try:
                candidates = json.loads(raw[start:end])
            except json.JSONDecodeError:
                logger.warning("Could not parse Claude response as JSON")
                return []
        else:
            logger.warning("Could not parse Claude response as JSON")
            return []

    for c in candidates:
        hook = c.get("hook", "")
        corrected_start = _find_word_start_for_hook(window.get("words", []), hook)
        if corrected_start is None:
            corrected_start = _find_segment_for_hook(window["segments"], hook)
        if corrected_start is not None:
            original_duration = c.get("end_sec", 0) - c.get("start_sec", 0)
            c["start_sec"] = corrected_start
            c["end_sec"] = corrected_start + max(original_duration, 30)
            logger.debug("Corrected timestamps for clip '%s': %.1fs", c.get("title", ""), corrected_start)
        else:
            logger.warning(
                "Could not match hook to transcript for clip '%s' — keeping Claude's timestamps",
                c.get("title", ""),
            )

    return candidates


def _deduplicate(candidates: list) -> list:
    """Keep highest-scored candidate when two clips overlap by more than 50%."""
    candidates = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
    kept = []
    for c in candidates:
        c_dur = c["end_sec"] - c["start_sec"]
        overlaps = False
        for k in kept:
            overlap = max(0.0, min(c["end_sec"], k["end_sec"]) - max(c["start_sec"], k["start_sec"]))
            shorter = min(c_dur, k["end_sec"] - k["start_sec"])
            if shorter > 0 and overlap / shorter > 0.5:
                overlaps = True
                break
        if not overlaps:
            kept.append(c)
    return kept


def _render_tier1_clip(clip_id: int, media_id: int):
    """
    Render one clip's 16:9 cut.
    Always increments clips_rendered so the progress counter never stalls.
    """
    from services.rendering import render_clip

    try:
        render_clip(clip_id)
    finally:
        increment_clips_rendered(media_id)


def _render_tier1(media_id: int, clips: list):
    """
    Process all clips through Tier 1 rendering with max 3 concurrent workers.
    Sets media status to 'ready' after the first 3 clips complete so the
    clips page can start showing results progressively.
    """
    logger.info("Starting Tier 1 rendering for media_id=%s (%d clips)", media_id, len(clips))
    threshold = min(3, len(clips))
    completed = 0
    first_ready_set = False

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_render_tier1_clip, c["id"], media_id): c["id"]
            for c in clips
        }
        for future in as_completed(futures):
            clip_id = futures[future]
            try:
                future.result()
                logger.info("Tier1 done: clip_id=%s", clip_id)
            except Exception as exc:
                logger.exception("Tier1 failed for clip_id=%s: %s", clip_id, exc)
            completed += 1
            if not first_ready_set and completed >= threshold:
                update_media_asset(media_id, status="ready")
                first_ready_set = True
                logger.info("First %d clips ready — media_id=%s now 'ready'", threshold, media_id)

    if not first_ready_set:
        update_media_asset(media_id, status="ready")
    logger.info("Tier 1 rendering complete for media_id=%s", media_id)


def analyze_media(media_id: int, context: str = ""):
    """
    Background task: sends transcript windows to Claude, stores clip candidates.
    Triggered via POST /api/media/{id}/analyze.
    """
    update_media_asset(media_id, status="analyzing")

    logger.info("Analyzing transcript for media_id=%s", media_id)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — cannot analyze media_id=%s", media_id)
        update_media_asset(media_id, status="transcribed")
        return

    transcript = get_transcript_by_media_id(media_id)
    if not transcript:
        logger.error("No transcript found for media_id=%s", media_id)
        update_media_asset(media_id, status="transcribed")
        return

    segments = json.loads(transcript["transcript_json"] or "[]")
    words = json.loads(transcript.get("words_json") or "[]")
    client = anthropic.Anthropic(api_key=api_key)

    try:
        windows = _build_windows(segments, words)
        logger.info("Analyzing %d windows for media_id=%s", len(windows), media_id)

        all_candidates = []
        for i, window in enumerate(windows):
            window_candidates = _analyze_window(client, window, context)
            all_candidates.extend(window_candidates)
            logger.info("Window %d/%d: found %d candidates", i + 1, len(windows), len(window_candidates))

        candidates = _deduplicate(all_candidates)
        logger.info("After deduplication: %d candidates for media_id=%s", len(candidates), media_id)

        delete_clips_by_media_id(media_id)

        for c in candidates:
            excerpt = _extract_excerpt(segments, c.get("start_sec", 0), c.get("end_sec", 0))
            create_clip_candidate(
                media_asset_id=media_id,
                start_sec=c.get("start_sec", 0),
                end_sec=c.get("end_sec", 0),
                title=c.get("title", ""),
                hook=c.get("hook", ""),
                reasoning=c.get("reasoning", ""),
                score=int(c.get("score", 0)),
                transcript_excerpt=excerpt,
            )

        logger.info("Analysis complete for media_id=%s — %d clips stored", media_id, len(candidates))

        clips = get_clips_by_media_id(media_id)
        update_media_asset(
            media_id,
            status="rendering",
            clips_total=len(clips),
            clips_rendered=0,
        )
        _render_tier1(media_id, clips)

    except Exception as exc:
        logger.exception("Analysis failed for media_id=%s: %s", media_id, exc)
        update_media_asset(media_id, status="transcribed")
