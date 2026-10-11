"""Self-check for the boundary and timecode logic: python3 test_clipper.py"""
from collections import Counter
from fractions import Fraction

from build_review import deduplicate, resolve, tokenize
from export import tc_to_frames

# 40 one-second words in 4 segments; only the 2nd and 4th end a sentence
text = [["w%d" % i for i in range(s * 10, s * 10 + 10)] for s in range(4)]
text[1][-1] += "."
text[3][-1] += "."
segments = [{"start": s * 10.0, "end": s * 10.0 + 10, "text": " ".join(t)} for s, t in enumerate(text)]
words = [{"word": w, "start": float(i), "end": i + 1.0} for i, w in enumerate(w for t in text for w in t)]

# quotes win over wrong numeric hints; start snaps to segment start, end walks to the sentence end
c = {"start_quote": "w12 w13 w14", "end_quote": "w24 w25 w26", "start_sec": 11, "end_sec": 27, "score": 8}
stats = Counter()
toks = tokenize(words)
assert resolve(c, segments, words, toks, stats) and (c["start_sec"], c["end_sec"]) == (10.0, 40.0), c
assert stats["snapped"] == 1

# unmatched quotes fall back to the numeric times; unusable ones are dropped
f = {"start_quote": "nope", "end_quote": "nada", "start_sec": 5, "end_sec": 30}
assert resolve(f, segments, words, toks, stats) and stats["fallback"] == 1
assert not resolve({"start_quote": "x", "end_quote": "y"}, segments, words, toks, stats)

# a hyphenated compound split by Whisper ('Nazi' + '-Keule,') must not shift the match
hw = [{"word": w, "start": float(i), "end": i + 1.0} for i, w in enumerate("Diese Nazi -Keule, die wird immer geschwungen".split())]
from build_review import match_quote
assert match_quote(tokenize(hw), "Diese Nazi-Keule, die wird immer") == (0, 5, 6)
assert match_quote(tokenize(hw), "Diese ganz andere Sache hier jetzt") is None   # 1 of 6 words is not a match

# overlapping clips: the higher score survives
kept = deduplicate([{"start_sec": 0, "end_sec": 30, "score": 5}, {"start_sec": 5, "end_sec": 35, "score": 9},
                    {"start_sec": 100, "end_sec": 130, "score": 1}])
assert [k["score"] for k in kept] == [9, 1]

# timecode: non-drop is plain counting; drop-frame skips 2 numbers per minute except every 10th
assert tc_to_frames("04:22:07:08", Fraction(60000, 1001)) == 943628
assert tc_to_frames("00:01:00;02", Fraction(30000, 1001)) == 1800
assert tc_to_frames("00:10:00;00", Fraction(30000, 1001)) == 17982
print("ok")
