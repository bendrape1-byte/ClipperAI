import json
import logging
import os
from collections import Counter
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

MIN_CLIP_SEC = 10       # resolved clips shorter than this fall back / get dropped
MAX_CLIP_SEC = 180      # hard cap on clip length and on the sentence-end forward walk
MIN_QUOTE_MATCH = 2     # minimum matched words for a quote anchor to count

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


def _match_quote(words: list, quote: str, min_idx: int = 0) -> Optional[tuple]:
    """
    Find the best consecutive run of word timestamps matching a verbatim quote.
    Normalizes via _clean_word, allows fuzzy containment either way, tolerates
    isolated mismatches inside the run. Returns (start_idx, end_idx, score) or
    None if fewer than MIN_QUOTE_MATCH words line up.
    """
    if not words or not quote:
        return None
    quote_words = [_clean_word(w) for w in quote.split()]
    quote_words = [w for w in quote_words if w]
    if not quote_words:
        return None
    best = None
    best_score = 0
    for i in range(min_idx, len(words)):
        wt = _clean_word(words[i]["word"])
        if not wt or not (wt == quote_words[0] or quote_words[0] in wt or wt in quote_words[0]):
            continue
        score = 1
        end_idx = i
        for j in range(1, len(quote_words)):
            if i + j >= len(words):
                break
            wt2 = _clean_word(words[i + j]["word"])
            qw = quote_words[j]
            if wt2 and (qw == wt2 or qw in wt2 or wt2 in qw):
                score += 1
                end_idx = i + j
        if score > best_score:
            best_score = score
            best = (i, end_idx, score)
    return best if best_score >= MIN_QUOTE_MATCH else None


def _snap_start(segments: list, t_start: float) -> float:
    """Start of the segment containing (or nearest before) t_start."""
    best = None
    for s in segments:
        if s["start"] <= t_start:
            best = s["start"]
        else:
            break
    return best if best is not None else t_start


def _snap_end(segments: list, t_end: float, snapped_start: float) -> Optional[float]:
    """
    End of the first segment at/after t_end whose text ends a sentence (. ! ?).
    The forward walk is capped at snapped_start + MAX_CLIP_SEC. If no sentence
    end exists within the cap (transcripts whose segments break mid-sentence),
    falls back to t_end itself — the end of the last quoted word — rather than
    a segment end that may include the dangling start of the next sentence.
    Returns None if t_end lies beyond every segment.
    """
    idx = None
    for i, s in enumerate(segments):
        if s["end"] >= t_end:
            idx = i
            break
    if idx is None:
        return None
    for s in segments[idx:]:
        if s["end"] - snapped_start > MAX_CLIP_SEC:
            break
        if s["text"].strip().endswith((".", "!", "?")):
            return s["end"]
    return t_end


def _resolve_boundaries(c: dict, window: dict, stats: Counter) -> bool:
    """
    Anchor a candidate to sentence boundaries: locate start_quote/end_quote in
    the window's word timestamps, snap both ends to segment boundaries, and
    overwrite c["start_sec"]/c["end_sec"]. Falls back to Claude's numeric times
    when matching fails; returns False if the candidate should be dropped.
    """
    words = window.get("words", [])
    segments = window["segments"]

    t_start = t_end = None
    m_start = _match_quote(words, c.get("start_quote", ""))
    if m_start:
        stats["start_match_ok"] += 1
        t_start = words[m_start[0]]["start"]
        m_end = _match_quote(words, c.get("end_quote", ""), min_idx=m_start[0] + 1)
    else:
        stats["start_match_fail"] += 1
        m_end = _match_quote(words, c.get("end_quote", ""))
    if m_end:
        stats["end_match_ok"] += 1
        t_end = words[m_end[1]]["end"]
    else:
        stats["end_match_fail"] += 1

    if t_start is not None and t_end is not None and t_end > t_start:
        start = _snap_start(segments, t_start)
        end = _snap_end(segments, t_end, start)
        if end is not None and MIN_CLIP_SEC <= end - start <= MAX_CLIP_SEC:
            c["start_sec"] = start
            c["end_sec"] = end
            c["boundary_method"] = "snapped"
            stats["snapped"] += 1
            return True

    start = c.get("start_sec")
    end = c.get("end_sec")
    if (
        isinstance(start, (int, float))
        and isinstance(end, (int, float))
        and MIN_CLIP_SEC <= end - start <= MAX_CLIP_SEC
    ):
        c["boundary_method"] = "fallback"
        stats["fallback"] += 1
        return True

    stats["dropped"] += 1
    return False


def _analyze_window(client, window: dict, context: str = "", stats: Optional[Counter] = None) -> list:
    """Send one transcript window to Claude and return boundary-resolved clip candidates."""
    if stats is None:
        stats = Counter()
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

Each clip must be a complete, self-contained thought: it must BEGIN at the start of a complete thought and END at the end of one — never mid-sentence. Mark its boundaries with two verbatim quotes:
- "start_quote": the exact first 6-10 words of the clip, copied word-for-word from the transcript above, marking where the clip BEGINS.
- "end_quote": the exact last 6-10 words of the clip, copied word-for-word from the transcript above, marking where the clip ENDS.
Copy both quotes EXACTLY as written in the transcript (same words, same order) so they can be located automatically. The quotes are authoritative for the clip boundaries; start_sec/end_sec are approximate hints only.

Return ONLY a valid JSON array, no other text, no markdown:
[
  {{
    "start_sec": <float — approximate second from transcript timestamps, hint only>,
    "end_sec": <float — approximate, hint only>,
    "start_quote": "<exact first 6-10 words of the clip, verbatim from the transcript>",
    "end_quote": "<exact last 6-10 words of the clip, verbatim from the transcript>",
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

    resolved = []
    for c in candidates:
        if _resolve_boundaries(c, window, stats):
            resolved.append(c)
        else:
            logger.warning(
                "Dropping clip '%s' — quotes unmatched and numeric times unusable",
                c.get("title", ""),
            )

    return resolved


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

        stats = Counter()
        all_candidates = []
        for i, window in enumerate(windows):
            window_candidates = _analyze_window(client, window, context, stats)
            all_candidates.extend(window_candidates)
            logger.info("Window %d/%d: found %d candidates", i + 1, len(windows), len(window_candidates))

        total = stats["snapped"] + stats["fallback"] + stats["dropped"]
        logger.info(
            "boundaries for media_id=%s: %d/%d snapped, %d fallback, %d dropped "
            "(start-match %d ok/%d fail, end-match %d ok/%d fail)",
            media_id, stats["snapped"], total, stats["fallback"], stats["dropped"],
            stats["start_match_ok"], stats["start_match_fail"],
            stats["end_match_ok"], stats["end_match_fail"],
        )

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
                boundary_method=c.get("boundary_method"),
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
