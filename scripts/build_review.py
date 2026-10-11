"""candidates.json (Claude's picks) + transcript.json -> clips.json + review.html. Stdlib only.

python3 build_review.py JOB_DIR
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

MIN_CLIP_SEC = 10       # resolved clips shorter than this fall back / get dropped
MAX_CLIP_SEC = 180      # hard cap on clip length and on the sentence-end forward walk
MIN_QUOTE_MATCH = 2     # minimum matched words for a quote anchor to count
MIN_QUOTE_RATIO = 0.6   # ...and at least this share of the quote's words
HINT_DRIFT_SEC = 20     # warn when a snapped start lands this far from Claude's approximate time
HINT_WINDOW_SEC = 120   # search for a quote this far around Claude's approximate time first


def _clean_word(w):
    return w.lower().strip('.,!?":;\'- ')


def _split(text):
    """Clean tokens, splitting hyphenated compounds: Whisper's word list splits
    'Nazi-Keule' into 'Nazi' + '-Keule' while the transcript text keeps it whole."""
    return [t for t in (_clean_word(x) for x in re.split(r"[\s\-]+", text or "")) if t]


def tokenize(words):
    """Flat [(token, word_index)] over the word timestamps."""
    return [(t, i) for i, w in enumerate(words) for t in _split(w["word"])]


def match_quote(toks, quote, lo=0, hi=None):
    """
    Find the best consecutive run of tokens matching a verbatim quote. Allows
    fuzzy containment either way and tolerates isolated mismatches inside the
    run. Returns (first_word_idx, last_word_idx, score), or None when fewer
    than MIN_QUOTE_MATCH words or under MIN_QUOTE_RATIO of the quote line up.
    """
    q = _split(quote)
    if not toks or not q:
        return None
    same = lambda a, b: a == b or a in b or b in a
    hi = len(toks) if hi is None else min(hi, len(toks))
    best, best_score = None, 0
    for i in range(lo, hi):
        if not same(toks[i][0], q[0]):
            continue
        score, end = 1, i
        for j in range(1, min(len(q), len(toks) - i)):
            if same(toks[i + j][0], q[j]):
                score, end = score + 1, i + j
        if score > best_score:
            best, best_score = (toks[i][1], toks[end][1], score), score
    return best if best_score >= max(MIN_QUOTE_MATCH, MIN_QUOTE_RATIO * len(q)) else None


def match_near(toks, words, quote, hint, min_word=0):
    """Match near the approximate time first so a repeated phrase elsewhere can't win."""
    first = next((k for k, (_, wi) in enumerate(toks) if wi >= min_word), len(toks))
    if isinstance(hint, (int, float)):
        lo = next((k for k, (_, wi) in enumerate(toks) if words[wi]["start"] >= hint - HINT_WINDOW_SEC), len(toks))
        hi = next((k for k, (_, wi) in enumerate(toks) if words[wi]["start"] > hint + HINT_WINDOW_SEC), len(toks))
        m = match_quote(toks, quote, max(lo, first), hi)
        if m:
            return m
    return match_quote(toks, quote, first)


def snap_start(segments, t_start):
    """Start of the segment containing (or nearest before) t_start."""
    best = None
    for s in segments:
        if s["start"] <= t_start:
            best = s["start"]
        else:
            break
    return best if best is not None else t_start


def snap_end(segments, t_end, snapped_start):
    """
    End of the first segment at/after t_end whose text ends a sentence (. ! ?),
    walking forward at most to snapped_start + MAX_CLIP_SEC. Falls back to t_end
    (end of the last quoted word) when no sentence end is in reach.
    """
    idx = next((i for i, s in enumerate(segments) if s["end"] >= t_end), None)
    if idx is None:
        return None
    for s in segments[idx:]:
        if s["end"] - snapped_start > MAX_CLIP_SEC:
            break
        if s["text"].strip().endswith((".", "!", "?")):
            return s["end"]
    return t_end


def resolve(c, segments, words, toks, stats):
    """Anchor a candidate to sentence boundaries via its quotes; False = drop it."""
    t_start = t_end = None
    hint = c.get("start_sec")
    m_start = match_near(toks, words, c.get("start_quote"), hint)
    if m_start:
        t_start = words[m_start[0]]["start"]
    m_end = match_near(toks, words, c.get("end_quote"), c.get("end_sec"), m_start[0] + 1 if m_start else 0)
    if m_end:
        t_end = words[m_end[1]]["end"]

    if t_start is not None and t_end is not None and t_end > t_start:
        start = snap_start(segments, t_start)
        end = snap_end(segments, t_end, start)
        if end is not None and MIN_CLIP_SEC <= end - start <= MAX_CLIP_SEC:
            c["start_sec"], c["end_sec"] = start, end
            c["method"] = "snapped"
            if isinstance(hint, (int, float)) and abs(start - hint) > HINT_DRIFT_SEC:
                c["method"] = "check: start moved %+.0fs from the hint" % (start - hint)
            stats["snapped"] += 1
            return True

    start, end = c.get("start_sec"), c.get("end_sec")
    if (isinstance(start, (int, float)) and isinstance(end, (int, float))
            and MIN_CLIP_SEC <= end - start <= MAX_CLIP_SEC):
        c["method"] = "fallback: quotes not found, using the approximate times"
        stats["fallback"] += 1
        return True
    stats["dropped"] += 1
    return False


def deduplicate(candidates):
    """Keep the highest-scored candidate when two clips overlap by more than 50%."""
    kept = []
    for c in sorted(candidates, key=lambda c: c.get("score", 0), reverse=True):
        c_dur = c["end_sec"] - c["start_sec"]
        for k in kept:
            overlap = max(0.0, min(c["end_sec"], k["end_sec"]) - max(c["start_sec"], k["start_sec"]))
            shorter = min(c_dur, k["end_sec"] - k["start_sec"])
            if shorter > 0 and overlap / shorter > 0.5:
                break
        else:
            kept.append(c)
    return kept


def excerpt(segments, start, end):
    return " ".join(s["text"].strip() for s in segments if s["start"] >= start and s["end"] <= end + 2)[:600]


def main():
    job = Path(sys.argv[1]).expanduser().resolve()
    source = Path(json.loads((job / "job.json").read_text())["source"])
    t = json.loads((job / "transcript.json").read_text())
    segments, words = t["segments"], t["words"]
    candidates = json.loads((job / "candidates.json").read_text())

    stats = Counter(snapped=0, fallback=0, dropped=0)
    toks = tokenize(words)
    resolved = [c for c in candidates if resolve(c, segments, words, toks, stats)]
    check = ["%s (%s)" % (c.get("title"), c["method"]) for c in resolved if c["method"] != "snapped"]
    clips = deduplicate(resolved)
    clips = [{
        "id": i, "title": c.get("title", "Clip %d" % i), "hook": c.get("hook", ""),
        "reasoning": c.get("reasoning", ""), "score": c.get("score", 0),
        "start": round(c["start_sec"], 3), "end": round(c["end_sec"], 3),
        "excerpt": excerpt(segments, c["start_sec"], c["end_sec"]),
    } for i, c in enumerate(clips, 1)]
    (job / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=2))

    data = {"job": str(job), "source_name": source.name, "source_url": source.as_uri(),
            "duration": segments[-1]["end"], "clips": clips,
            # every word with its time, so the trim bar can show what the clip starts and ends on
            "words": [[round(w["start"], 2), round(w["end"], 2), w["word"]] for w in words]}
    template = (Path(__file__).parent / "review_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (job / "review.html").write_text(template.replace("__DATA__", payload), encoding="utf-8")
    print(json.dumps({"review": str(job / "review.html"), "clips": len(clips), **stats, "check": check},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
