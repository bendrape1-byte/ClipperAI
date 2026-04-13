"""
services/broll.py — B-roll suggestion (Claude + Pexels) and ffmpeg compositing.

Phase A: suggest_broll()
  - Sends transcript to Claude → gets timestamped moments
  - Searches Pexels for each moment → downloads best matching clip
  - Stores results in broll_suggestions table

Phase B: composite_broll()
  - Takes all approved suggestions for a clip
  - Looks up the clip's profile for transition_style and transition_sfx_id
  - Builds a filter_complex that replaces the video track at each timestamp
  - Outputs storage/clips/{id}_broll.mp4 (and vertical variant if 9:16 exists)

Transition styles:
  crossfade    — fade=out on A-roll end + fade=in on B-roll start, 0.15 s each
  dip_to_black — same fade approach, 0.25 s (slower, more cinematic black dip)
  wipe_left    — falls back to fade approach (xfade wipes require timebase matching)
  cut          — hard cut everywhere, no fade filters

All styles use concat for assembly, which tolerates mismatched timebases and frame
rates. xfade was removed because ffmpeg 8.1's filter negotiation sees the pre-settb
timebase on one input even after settb is applied, causing consistent failures.

SFX timing:
  crossfade / dip_to_black — SFX fires 0.05 s before B-roll entry
  wipe_left / cut          — SFX fires at the cut point
"""

import json
import logging
import os
import re
import subprocess

import anthropic
import requests

from config import BROLL_DIR, CLIPS_DIR
from database import (
    create_broll_suggestion,
    get_approved_broll_for_clip,
    get_broll_suggestion,
    get_broll_suggestions_for_clip,
    get_clip_candidate,
    update_broll_suggestion,
    update_clip_candidate,
)
from services.reframe import get_video_dimensions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transition constants
# ---------------------------------------------------------------------------

# Fade duration (seconds) per style, applied as fade=out on A-roll and
# fade=in on B-roll independently — no xfade, so timebases don't need to match.
_FADE_DUR = {
    "crossfade":    0.15,
    "dip_to_black": 0.25,
    "wipe_left":    0.15,   # wipe requires xfade; fall back to fade
    "cut":          0.0,    # no fade filter at all
}

# How many seconds BEFORE the B-roll entry point to fire the SFX.
_SFX_LEAD = {
    "crossfade":    0.05,
    "dip_to_black": 0.05,
    "wipe_left":    0.05,
    "cut":          0.05,
}

# ---------------------------------------------------------------------------
# Claude / Pexels prompts
# ---------------------------------------------------------------------------

_BROLL_SYSTEM_PROMPT = (
    "You are a professional short-form video editor. Your job is to decide exactly "
    "where B-roll footage should be placed over a talking-head clip to maximize viewer retention."
)

_BROLL_USER_PROMPT = """\
CLIP CONTEXT (use this to write better search queries — not to decide placement):
- Title: {title}
- Host: {host_name}
- Guest: {guest_name}
- Topic: {topic}

CLIP DURATION: {duration:.1f}s
TRANSCRIPT WITH WORD TIMESTAMPS:
{word_timestamped_transcript}

YOUR TASK:
Find sentences where B-roll would INSTANTLY and OBVIOUSLY make sense.

THE FILMABILITY TEST — ask yourself for each sentence:
"Could a cameraman point a camera at the thing being described and film it in real life?"
- YES → suggest B-roll. Examples: "walking through the city", "typing on a laptop", "a crowded market", "driving a car", "cooking in a kitchen", "a sunset over the ocean"
- NO → skip it. Examples: "Isaac Newton discovered gravity" (can't film Isaac Newton), "the concept of freedom" (abstract), "he felt betrayed" (emotion, not filmable), "the algorithm works differently" (abstract process), "back in 2015" (can't film the past)

CRITICAL RULES:
1. ONLY suggest B-roll for concretely filmable things. If you have to think about it for more than 2 seconds, it's not obvious enough — skip it.
2. Stock footage sites have: nature, cities, people doing activities, technology/devices, food, sports, business scenes, transportation, buildings. They do NOT have: specific historical figures, abstract concepts, specific brands/products, specific people, specific events.
3. B-roll MUST start at the exact first word of the relevant phrase and end at the exact last word. Use the word timestamps to set precise start_sec and end_sec. Do not add padding before or after.
4. Each B-roll segment should cover exactly the sentence or phrase it illustrates — not longer, not shorter.
5. Target density: suggest B-roll for roughly 30-50% of the clip duration. Skip sentences that aren't filmable rather than forcing bad B-roll.
6. NEVER place B-roll on the first 3 seconds or last 2 seconds of the clip.
7. If two B-roll moments are less than 1.5 seconds apart, merge them or drop the weaker one.

SEARCH QUERY RULES:
1. Describe what the camera would literally see. Not the topic — the SHOT.
   - BAD: "success" "business" "Newton" "philosophy" "motivation"
   - GOOD: "person walking on busy street" "close up hands typing keyboard" "aerial view city skyline night" "coffee shop counter barista"
2. Be specific about the camera angle/framing when possible: "close up", "aerial view", "wide shot", "timelapse"
3. Provide THREE queries per suggestion, ordered from most specific to broadest fallback

Return ONLY a valid JSON array, no other text. Each element:
{{"start_sec": float, "end_sec": float, "start_word": "exact first word of phrase", "end_word": "exact last word of phrase", "reason": "one sentence: what filmable thing is being described", "search_queries": ["specific shot description", "medium description", "broad fallback"], "confidence": "high or medium"}}

Only return "high" and "medium" confidence items. "high" = obviously filmable with obvious stock footage. "medium" = probably filmable but less certain.
"""

_SWAP_QUERY_PROMPT = """\
A video editor wants to replace a B-roll clip. The original moment in the clip:
"{reason}"

The editor typed this search term: "{user_query}"

Generate 2 alternative search queries that might find better footage for this moment.
Be hyper-specific and visual — describe filmable, concrete things.
Return ONLY a JSON array of 2 strings, no other text: ["query one", "query two"]
"""


# ---------------------------------------------------------------------------
# Pexels helpers
# ---------------------------------------------------------------------------

def _search_pexels_raw(query: str, orientation: str = "landscape", per_page: int = 2) -> list:
    """Return up to `per_page` raw video dicts from Pexels, or raise on error."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise ValueError("PEXELS_API_KEY environment variable is not set.")

    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": orientation, "per_page": per_page},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError(
            "Pexels API rate limit reached (200 requests/hour). Wait before retrying."
        )
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _score_video(video: dict, prefer_portrait: bool = False) -> int:
    """Score a Pexels video candidate. Higher is better."""
    score = 0
    dur = video.get("duration", 0)
    if 4 <= dur <= 12:
        score += 2
    elif 3 <= dur <= 15:
        score += 1
    else:
        score -= 2

    # Resolution from best file
    best = _best_video_file(video)
    if best:
        w = best.get("width", 0)
        h = best.get("height", 0)
        longer = max(w, h)
        if longer >= 1080:
            score += 1
        elif longer < 720:
            score -= 1

        # Orientation preference
        is_portrait = h > w
        if prefer_portrait and is_portrait:
            score += 1
        elif not prefer_portrait and not is_portrait:
            score += 1

    return score


def _best_video_file(video: dict) -> dict:
    files = video.get("video_files", [])
    hd = [f for f in files if f.get("quality") == "hd"] or files
    if not hd:
        return None
    return min(hd, key=lambda f: abs(f.get("width", 0) - 1920) + abs(f.get("height", 0) - 1080))


def _search_best_pexels(queries: list, orientation: str = "landscape"):
    """
    Search all queries (up to 2 results each), score every candidate,
    return the best (video, video_file) pair or (None, None) if none pass quality.
    """
    candidates = []
    prefer_portrait = orientation == "portrait"

    for query in queries:
        try:
            videos = _search_pexels_raw(query, orientation=orientation, per_page=2)
        except RuntimeError:
            raise  # propagate rate-limit so caller can break
        except Exception:
            continue  # network error on one query — skip, try next

        for video in videos:
            vf = _best_video_file(video)
            if not vf:
                continue
            # Minimum quality gate: ≥720p, ≥3s
            if max(vf.get("width", 0), vf.get("height", 0)) < 720:
                continue
            if video.get("duration", 0) < 3:
                continue
            candidates.append((video, vf, _score_video(video, prefer_portrait)))

    if not candidates:
        return None, None

    candidates.sort(key=lambda t: t[2], reverse=True)
    best_video, best_file, _ = candidates[0]
    return best_video, best_file


def _download_video(url: str, dest_path: str):
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)


_STOP_WORDS = {"a", "an", "the", "of", "in", "on", "at", "to", "for",
               "with", "and", "or", "is", "are", "by", "as", "up"}

def _pexels_result_is_relevant(video: dict, queries: list) -> bool:
    """
    Sanity-check that the best Pexels result is plausibly related to the
    search queries.  Extracts the title slug from the Pexels URL and checks
    whether any meaningful query keyword appears in it.

    Returns True (accept) when there is keyword overlap OR when we can't
    extract enough signal to make a judgment.
    """
    url  = video.get("url", "")
    slug = url.rstrip("/").split("/")[-1]          # "city-skyline-at-night-3222810"
    slug = re.sub(r"-\d+$", "", slug)              # strip trailing ID number
    slug_words = set(slug.replace("-", " ").lower().split())

    query_words = set()
    for q in queries:
        for w in q.lower().split():
            if len(w) > 3 and w not in _STOP_WORDS:
                query_words.add(w)

    if not query_words:
        return True   # nothing to validate against — accept
    return bool(query_words & slug_words)


# ---------------------------------------------------------------------------
# Phase A: suggestion
# ---------------------------------------------------------------------------

def suggest_broll(clip_id: int):
    """
    Background task: use Claude to find B-roll moments, search Pexels, download clips.
    Creates broll_suggestion rows for each successful result.

    Sends word-level timestamps to Claude so it can snap B-roll boundaries to
    exact spoken words rather than guessing.  Filters by confidence and validates
    each Pexels result against the search queries before downloading.
    """
    from database import get_media_asset, get_clip_profile, get_transcript_by_media_id

    clip = get_clip_candidate(clip_id)
    if not clip:
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("suggest_broll: ANTHROPIC_API_KEY not set")
        return

    duration    = clip["end_sec"] - clip["start_sec"]
    clip_start  = clip["start_sec"]
    clip_end    = clip["end_sec"]

    # Profile context — improves search query tone without affecting placement logic
    title = clip.get("title") or "Untitled"
    host_name = guest_name = topic = "—"
    media = get_media_asset(clip["media_asset_id"])
    if media and media.get("profile_id"):
        profile = get_clip_profile(media["profile_id"])
        if profile:
            host_name  = profile.get("host_name") or "—"
            guest_name = profile.get("guest_name") or "—"
            topic      = profile.get("topic") or "—"

    # ── Build word-timestamped transcript ─────────────────────────────────
    transcript_row = get_transcript_by_media_id(clip["media_asset_id"])
    all_words = json.loads((transcript_row or {}).get("words_json") or "[]")

    # Filter to words within the clip's time range and normalise to clip-relative time
    clip_words = []
    for w in all_words:
        ws = float(w.get("start", 0))
        we = float(w.get("end", 0))
        if ws >= clip_start - 0.1 and we <= clip_end + 0.1:
            clip_words.append({
                "word":  w["word"].strip(),
                "start": round(ws - clip_start, 2),
            })

    if clip_words:
        word_timestamped_transcript = " ".join(
            f"[{w['start']:.2f}] {w['word']}" for w in clip_words
        )
    else:
        # Fallback: plain transcript without timing
        word_timestamped_transcript = (clip.get("transcript_excerpt") or "").strip()

    if not word_timestamped_transcript:
        logger.warning("suggest_broll: no transcript data for clip_id=%s", clip_id)
        return

    # ── Ask Claude ─────────────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            system=_BROLL_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": _BROLL_USER_PROMPT.format(
                    title=title,
                    host_name=host_name,
                    guest_name=guest_name,
                    topic=topic,
                    duration=duration,
                    word_timestamped_transcript=word_timestamped_transcript,
                ),
            }],
        )
        raw  = response.content[0].text.strip()
        s, e = raw.find("["), raw.rfind("]") + 1
        suggestions = json.loads(raw[s:e]) if s != -1 else []
        if not isinstance(suggestions, list):
            suggestions = []
    except Exception as exc:
        logger.exception("suggest_broll: Claude call failed for clip_id=%s: %s", clip_id, exc)
        return

    logger.info(
        "suggest_broll: Claude returned %d suggestions for clip_id=%s",
        len(suggestions), clip_id,
    )

    # ── Filter by confidence: prefer "high", include "medium" only if needed ──
    high   = [s for s in suggestions if s.get("confidence") == "high"]
    medium = [s for s in suggestions if s.get("confidence") == "medium"]
    filtered = high if len(high) >= 2 else high + medium
    logger.info(
        "suggest_broll: %d high + %d medium → using %d for clip_id=%s",
        len(high), len(medium), len(filtered), clip_id,
    )

    for i, s in enumerate(filtered):
        queries = s.get("search_queries") or []
        if isinstance(queries, str):
            queries = [queries]
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        if not queries:
            continue

        start_sec  = float(s.get("start_sec", 0))
        end_sec    = float(s.get("end_sec", start_sec + 3))
        reason     = s.get("reason", "")
        start_word = s.get("start_word", "")
        end_word   = s.get("end_word", "")

        # Clamp to safe clip range (no B-roll in first 3s or last 2s)
        start_sec = max(3.0, min(start_sec, duration - 2))
        end_sec   = max(start_sec + 2.0, min(end_sec, duration - 2))
        if start_sec >= end_sec:
            continue

        try:
            video, video_file = _search_best_pexels(queries, orientation="landscape")
            if not video or not video_file:
                logger.info(
                    "suggest_broll: skipped at %.1fs — no Pexels result for clip_id=%s queries=%r",
                    start_sec, clip_id, queries,
                )
                continue

            # Reject results that share no keywords with the queries
            if not _pexels_result_is_relevant(video, queries):
                logger.info(
                    "suggest_broll: skipped B-roll at %.1fs — Pexels result irrelevant "
                    "for clip_id=%s queries=%r url=%s",
                    start_sec, clip_id, queries, video.get("url", ""),
                )
                continue

            dest_path = os.path.join(BROLL_DIR, f"{clip_id}_{i}.mp4")
            _download_video(video_file["link"], dest_path)

            create_broll_suggestion(
                clip_id=clip_id,
                start_sec=start_sec,
                end_sec=end_sec,
                search_query=queries[0],
                reason=reason,
                pexels_video_id=video["id"],
                pexels_url=video.get("url", ""),
                pexels_thumbnail_url=video.get("image", ""),
                photographer_name=(video.get("user") or {}).get("name", ""),
                broll_file_path=dest_path,
                search_queries=json.dumps(queries),
                start_word=start_word,
                end_word=end_word,
            )
            logger.info(
                "suggest_broll: saved clip_id=%s start=%.2fs (%r) end=%.2fs (%r) queries=%r",
                clip_id, start_sec, start_word, end_sec, end_word, queries,
            )

        except RuntimeError as exc:
            logger.error("suggest_broll: Pexels rate limit for clip_id=%s: %s", clip_id, exc)
            break
        except Exception as exc:
            logger.exception(
                "suggest_broll: failed for clip_id=%s queries=%r: %s", clip_id, queries, exc
            )


# ---------------------------------------------------------------------------
# Phase B: compositing helpers
# ---------------------------------------------------------------------------

def _scale_filter(w: int, h: int) -> str:
    """
    ffmpeg scale filter that fits any input into w×h.
    Portrait target: fill height, center-crop width (landscape B-roll → portrait).
    Landscape target: scale to fit, letterbox with black bars.
    """
    if h > w:
        return f"scale=-2:{h},crop={w}:{h}:(iw-{w})/2:0"
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    )


def _build_composite_filter(
    suggestions: list,
    w: int,
    h: int,
    total_duration: float,
    transition_style: str = "crossfade",
) -> tuple:
    """
    Build the filter_complex string for B-roll compositing.

    Input 0    = source clip
    Input 1..n = B-roll clips (same order as suggestions list)

    Transitions are implemented as per-segment fade=out / fade=in filters applied
    before all segments are joined by concat.  concat tolerates mismatched timebases
    and frame rates, so no settb or timebase normalisation is needed.

    A→B entry: fade=out on the A-roll tail + fade=in on the B-roll head.
    B→A return: always a hard cut (no fade).
    cut style: no fade filters at all.

    Returns (filter_str, total_duration).  Duration is never shortened.
    """
    scale    = _scale_filter(w, h)
    fade_dur = _FADE_DUR.get(transition_style, 0.15)
    use_fade = fade_dur > 0

    trim_parts = []
    seg_labels = []   # ordered list of output labels for the final concat

    prev_end = 0.0
    for i, s in enumerate(suggestions):
        broll_input = i + 1
        broll_dur   = s["end_sec"] - s["start_sec"]

        # A-roll segment before this B-roll
        if s["start_sec"] > prev_end + 0.02:
            # Extend trim end by fade_dur so the fade-out starts exactly at
            # start_sec (the speaker is fully visible right up to that point).
            # Without this extension the fade-out would begin fade_dur seconds
            # BEFORE start_sec, making the screen go dark before the word.
            a_trim_end = s["start_sec"] + fade_dur if use_fade else s["start_sec"]
            a_dur      = a_trim_end - prev_end
            lbl        = f"[o{i}]"
            fade_o = (
                f",fade=t=out:st={max(0.0, a_dur - fade_dur):.4f}:d={fade_dur:.4f}"
                if use_fade else ""
            )
            trim_parts.append(
                f"[0:v]trim=start={prev_end:.4f}:end={a_trim_end:.4f},"
                f"setpts=PTS-STARTPTS,fps=25,setsar=1{fade_o}{lbl}"
            )
            seg_labels.append(lbl)

        # B-roll segment
        lbl    = f"[b{i}]"
        fade_i = f",fade=t=in:st=0:d={fade_dur:.4f}" if use_fade else ""
        trim_parts.append(
            f"[{broll_input}:v]trim=end={broll_dur:.4f},"
            f"setpts=PTS-STARTPTS,fps=25,{scale},setsar=1{fade_i}{lbl}"
        )
        seg_labels.append(lbl)
        prev_end = s["end_sec"]

    # Tail A-roll after the last B-roll (B→A is always a hard cut)
    if prev_end < total_duration - 0.02:
        lbl = "[o_tail]"
        trim_parts.append(
            f"[0:v]trim=start={prev_end:.4f}:end={total_duration:.4f},"
            f"setpts=PTS-STARTPTS,fps=25,setsar=1{lbl}"
        )
        seg_labels.append(lbl)

    if not seg_labels:
        return None, total_duration

    if len(seg_labels) == 1:
        chain = f"{seg_labels[0]}setpts=PTS[vout]"
    else:
        chain = f"{''.join(seg_labels)}concat=n={len(seg_labels)}:v=1:a=0[vout]"

    return ";".join(trim_parts + [chain]), total_duration


def _build_audio_filter(
    suggestions: list,
    sfx_input_idx: int,
    transition_style: str,
    audio_src: str,
) -> str:
    """
    Layer the chosen SFX at each B-roll entry point.
    audio_src is the ffmpeg stream label for the main audio (e.g. '[0:a]' or '[atrimmed]').
    Only suggestions with transition_sfx=1 get the sound.
    """
    lead = _SFX_LEAD.get(transition_style, 0.05)
    sfx_subs = [s for s in suggestions if s.get("transition_sfx", 1)]

    parts  = []
    labels = []
    for i, s in enumerate(sfx_subs):
        delay_sec = max(0.0, s["start_sec"] - lead)
        delay_ms  = int(delay_sec * 1000)
        lbl = f"[w{i}]"
        parts.append(f"[{sfx_input_idx}:a]adelay={delay_ms}:all=1,volume=0.3{lbl}")
        labels.append(lbl)

    n_inputs = len(labels) + 1  # main audio + each SFX copy
    parts.append(
        f"{audio_src}{''.join(labels)}amix=inputs={n_inputs}:duration=first:normalize=0[aout]"
    )
    return ";".join(parts)


def _run_composite(
    source: str,
    suggestions: list,
    output_path: str,
    sfx_path=None,
    transition_style: str = "crossfade",
) -> bool:
    """Run ffmpeg composite and return True on success."""
    w, h = get_video_dimensions(source)
    total_duration = float(subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", source],
        capture_output=True, text=True,
    ).stdout.strip())

    video_filter, _ = _build_composite_filter(
        suggestions, w, h, total_duration, transition_style
    )
    if video_filter is None:
        logger.error("_run_composite: no filter produced for %s", source)
        return False

    sfx_suggestions = [s for s in suggestions if s.get("transition_sfx", 1)]
    use_sfx = bool(sfx_path and os.path.exists(sfx_path) and sfx_suggestions)

    cmd = ["ffmpeg", "-i", source]
    for s in suggestions:
        cmd += ["-i", s["broll_file_path"]]

    if use_sfx:
        # Mix SFX into the original audio track
        cmd += ["-i", sfx_path]
        sfx_input_idx = len(suggestions) + 1
        audio_filter  = _build_audio_filter(
            sfx_suggestions, sfx_input_idx, transition_style, "[0:a]"
        )
        filter_complex = f"{video_filter};{audio_filter}"
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-y", output_path,
        ]
    else:
        # No SFX — copy the original audio stream unchanged
        cmd += [
            "-filter_complex", video_filter,
            "-map", "[vout]",
            "-map", "0:a",
            "-c:v", "libx264", "-crf", "22", "-preset", "fast",
            "-c:a", "copy",
            "-y", output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("composite_broll ffmpeg failed:\n%s", result.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Phase B: public entry point
# ---------------------------------------------------------------------------

def composite_broll(clip_id: int):
    """
    Background task: composite all approved B-roll suggestions into the rendered clip.
    Produces storage/clips/{id}_broll.mp4 (and vertical variant if 9:16 exists).
    Transition style and SFX are resolved from the clip's profile (or defaults).
    """
    from database import get_media_asset, get_clip_profile, get_sfx_entry, get_default_sfx

    clip = get_clip_candidate(clip_id)
    if not clip:
        return

    # --- Resolve transition style and SFX from profile ---
    transition_style = "crossfade"
    sfx_path = None

    media = get_media_asset(clip["media_asset_id"])
    if media and media.get("profile_id"):
        profile = get_clip_profile(media["profile_id"])
        if profile:
            transition_style = profile.get("transition_style") or "crossfade"
            sfx_id = profile.get("transition_sfx_id")
            sfx_entry = get_sfx_entry(sfx_id) if sfx_id else get_default_sfx("transition")
            if sfx_entry and sfx_entry.get("file_path") and os.path.exists(sfx_entry["file_path"]):
                sfx_path = sfx_entry["file_path"]

    if sfx_path is None:
        sfx_entry = get_default_sfx("transition")
        if sfx_entry and sfx_entry.get("file_path") and os.path.exists(sfx_entry["file_path"]):
            sfx_path = sfx_entry["file_path"]

    suggestions = get_approved_broll_for_clip(clip_id)
    if not suggestions:
        logger.warning("composite_broll: no approved suggestions for clip_id=%s", clip_id)
        return

    missing = [s for s in suggestions if not s.get("broll_file_path") or
               not os.path.exists(s["broll_file_path"])]
    if missing:
        logger.error("composite_broll: %d B-roll file(s) missing for clip_id=%s", len(missing), clip_id)
        return

    for s in suggestions:
        logger.info(
            "composite_broll: clip_id=%s placing B-roll at %.2fs–%.2fs (start_word=%r end_word=%r)",
            clip_id, s["start_sec"], s["end_sec"],
            s.get("start_word", ""), s.get("end_word", ""),
        )

    updates = {}

    # 16:9 composite
    preview = clip.get("preview_path")
    if preview and os.path.exists(preview):
        out = os.path.join(CLIPS_DIR, f"{clip_id}_broll.mp4")
        if _run_composite(preview, suggestions, out, sfx_path, transition_style):
            updates["broll_path"] = out
            logger.info("composite_broll: 16:9 complete for clip_id=%s", clip_id)

    # 9:16 composite (center-crops landscape B-roll to portrait)
    vertical = clip.get("vertical_path")
    if vertical and os.path.exists(vertical):
        out = os.path.join(CLIPS_DIR, f"{clip_id}_vertical_broll.mp4")
        if _run_composite(vertical, suggestions, out, sfx_path, transition_style):
            updates["vertical_broll_path"] = out
            logger.info("composite_broll: 9:16 complete for clip_id=%s", clip_id)

    if updates:
        update_clip_candidate(clip_id, **updates)
    else:
        logger.error("composite_broll: nothing produced for clip_id=%s", clip_id)


# ---------------------------------------------------------------------------
# Swap helper (called synchronously from the route handler)
# ---------------------------------------------------------------------------

def swap_broll(suggestion_id: int, new_query: str) -> dict:
    """
    Replace the Pexels video for a suggestion with a new search query.
    Uses Claude to generate 2 additional query variants, searches all 3,
    picks the best result. Downloads, updates DB, resets status to 'suggested'.
    Returns the updated suggestion dict, or raises on failure.
    """
    suggestion = get_broll_suggestion(suggestion_id)
    if not suggestion:
        raise ValueError(f"Suggestion {suggestion_id} not found")

    reason = suggestion.get("reason") or ""
    queries = [new_query]

    # Ask Claude for 2 alternative queries
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": _SWAP_QUERY_PROMPT.format(
                        reason=reason, user_query=new_query
                    ),
                }],
            )
            raw = response.content[0].text.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            extras = json.loads(raw[start:end]) if start != -1 else []
            if isinstance(extras, list):
                queries += [q.strip() for q in extras if isinstance(q, str) and q.strip()]
        except Exception as exc:
            logger.warning("swap_broll: Claude query expansion failed: %s", exc)

    video, video_file = _search_best_pexels(queries, orientation="landscape")
    if not video or not video_file:
        raise LookupError(f"No usable Pexels results for queries: {queries!r}")

    clip_id  = suggestion["clip_id"]
    existing = suggestion.get("broll_file_path") or ""
    dest_path = existing if existing else os.path.join(
        BROLL_DIR, f"{clip_id}_swap_{suggestion_id}.mp4"
    )

    _download_video(video_file["link"], dest_path)

    update_broll_suggestion(
        suggestion_id,
        search_query=new_query,
        search_queries=json.dumps(queries),
        pexels_video_id=video["id"],
        pexels_url=video.get("url", ""),
        pexels_thumbnail_url=video.get("image", ""),
        photographer_name=(video.get("user") or {}).get("name", ""),
        broll_file_path=dest_path,
        status="suggested",
    )

    return get_broll_suggestion(suggestion_id)
