---
name: clipper
description: Find the best short-form clips in a long video (podcast, interview, talk) and hand them to an editor as a Premiere timeline or lossless clip files for CapCut. Runs fully local with no API keys - local Whisper transcription, clip selection by Claude, no video encoding. Use when the user gives a video file or YouTube link and wants clips, clip ideas, highlights, shorts, reels, or says "clip this", "find clips", "/clipper".
---

# Clipper

Pipeline: **transcribe locally → pick clips → editor reviews in the browser → export.**
Nothing is rendered. Previews play straight from the source file; export is a Premiere timeline
or a lossless stream copy.

`SKILL_DIR` below is the folder containing this file. Every job lives in `~/Movies/Clipper/<name>/`.

## 0. Setup (first run on a machine, or when `SKILL_DIR/config.json` is missing)

1. Run `python3 SKILL_DIR/scripts/setup.py` and read the JSON.
2. Tell the user in one or two sentences what their machine is and what you are about to install
   (everything in `installs_into_skill_folder`, and the model size from `note`). It all goes into this
   skill's own folder; nothing is installed system-wide. Then run each entry of `commands` in order.
   Do not ask them to run anything themselves.
3. Run `python3 SKILL_DIR/scripts/setup.py --write`. It must report `"ready": true` and write `config.json`.
4. If `config.backend` is `"none"`, the machine is too weak for local transcription. Tell the user they
   need a subtitle file (`.srt`) for each video, from any transcription service, and use the `--srt` path below.

## 1. Transcribe

Use the venv python from `config.json` (`"python"`):

```
<python> SKILL_DIR/scripts/transcribe.py "<file path or YouTube URL>"
<python> SKILL_DIR/scripts/transcribe.py "<file>" --srt "<subtitles.srt>"     # weak machine
```

With a link on macOS, the script first hands it to the user's 4K Video Downloader (it copies the link,
triggers the app's Paste Link command and waits for the app to finish), so the file arrives in the
quality the editor has set there. Tell the user the app will open and that macOS may ask once for
permission to control it. If the app is missing or does not take the link, the script falls back to
its own downloader (H.264, max 1080p; `--no-4k --best` for the top format). If both fail, do not
debug: ask the user to download the video in 4K Video Downloader by hand and continue with that file.
Files from that app land in `~/Movies/4K Video Downloader+/`; if the user names a video without
giving a path, look there.

Run it in the background for long videos and tell the user it is running; the first run also downloads
the model. It prints the job folder. If the user named the
guests or the show, pass the names with `--prompt "Name One, Name Two, special terms"` so Whisper
spells them correctly.

## 2. Pick clips

Read `<job>/transcript.txt` in full (lines look like `[HH:MM:SS] text`), in chunks of about 400 lines;
a two-hour video is around 4000 lines. If the user gave context about the show, guest or audience, use
it to inform scoring. There are no speaker labels, so infer who is talking from the content. Then
apply this brief exactly:

> You are an expert short-form video strategist and editor. You identify moments in podcast transcripts that will perform as standalone clips on Instagram Reels, TikTok, and YouTube Shorts.
>
> HOOKS — the first 3 seconds determine whether someone scrolls past:
> Strong hooks: bold contrarian claim ("most people are wrong about X"), specific surprising number, curiosity gap ("what nobody tells you about X"), story open-loop ("the day I almost lost everything"), direct value promise ("in 60 seconds here's exactly how to X")
> Weak hooks: "So today I want to talk about...", "That's a really great question", "You know, I think...", "It's interesting because...", anything that requires prior context to understand
>
> WHAT PERFORMS ON SHORT-FORM:
> - Contrarian or counter-intuitive takes that challenge conventional wisdom
> - Specific concrete results with numbers ("went from 0 to $10k in 47 days")
> - Genuine emotion: frustration, revelation, laughter — not performed enthusiasm
> - Clear insight moments where something clicks ("oh, so THAT'S why...")
> - List formats with a strong opener ("3 things that will kill your startup")
> - Vulnerability paired with a hard-won lesson
> - Bold, confident statements without hedging or over-qualifying
> - Stories with a clear arc: setup → tension → resolution, all within the clip
>
> WHAT KILLS RETENTION:
> - Starting mid-thought or referencing anything said earlier in the conversation
> - Over-qualifying every claim: "it depends", "kind of", "maybe", "I guess", "sort of"
> - More than 2 seconds without new information or forward momentum
> - Trailing endings — the clip must land on something, not just stop
> - Clips where you need to know the speaker to understand why the insight matters
> - Academic or jargon-heavy language without immediate plain-language translation
>
> SCORING GUIDE:
> 9-10: Exceptional hook + self-contained + strong landing + would stop a scroll cold
> 7-8: Strong hook, clear value, minor issues with pacing or landing
> 5-6: Decent content but weak hook or requires slight context
> 3-4: Interesting topic but poor clip boundaries or requires too much setup
> 1-2: Would not perform — ignore these
>
> IDEAL STRUCTURE: Hook (0–3s grabs attention) → delivers on the hook's promise with specifics → lands on a strong final statement
> SWEET SPOT: 35–65 seconds. Under 30s only if the insight is razor-sharp. Over 75s needs exceptional narrative momentum to hold.

Find roughly 3-6 candidates per 15 minutes of video. Be selective and apply the scoring guide strictly;
leave out anything scoring below 6. Each clip must begin at the start of a complete thought and end at
the end of one, never mid-sentence. Skip cold-open teasers that replay later passages (clip the
original passage instead) and skip sponsor reads.

Write `<job>/candidates.json` as a JSON array:

```json
[{
  "start_sec": 312.0,
  "end_sec": 371.0,
  "start_quote": "exact first 6-10 words of the clip, verbatim from the transcript",
  "end_quote": "exact last 6-10 words of the clip, verbatim from the transcript",
  "title": "5-8 word descriptive title",
  "hook": "the exact opening sentence of this clip",
  "reasoning": "one sentence: why this works as a standalone clip",
  "score": 8
}]
```

The quotes are authoritative for the boundaries, so copy them word for word from the transcript,
including its spelling mistakes. A quote may run across line and sentence breaks. `start_sec` is the
timestamp of the line the clip starts on and `end_sec` the timestamp of the line after it ends; they
only need to be within a few seconds, but they matter: the quote is searched for near them, which
keeps a phrase that also occurs elsewhere from matching in the wrong place.
Write titles, hooks and reasoning in the language of the video, with names and garbled words corrected.

## 3. Build the review page

```
python3 SKILL_DIR/scripts/build_review.py "<job>"
```

It snaps every clip to sentence boundaries using the word timestamps, removes overlapping duplicates and
writes `<job>/review.html` and `<job>/clips.json` (final `start` / `end` in seconds). Check the printed
result: `fallback` and `dropped` count clips whose quotes were not found, and `check` lists clips that
were found far from their hint or fell back. Fix the quotes or hints of anything in `check` in
`candidates.json` and rerun until it is empty.

Open the page for the user (`open "<job>/review.html"` on macOS, `start` on Windows) and tell them:
preview each clip, drag the ends of the trim bar to set the in and out points, press Approve, then press
**Copy approved clips** and
paste the result back here.

## 4. Export

When the user pastes the approved list, save its JSON object (the part after "Export these clips:")
as `<job>/approved.json`. Ask which editor it is for if they have not said, then:

```
python3 SKILL_DIR/scripts/export.py "<job>" --premiere    # premiere.xml: File > Import in Premiere
python3 SKILL_DIR/scripts/export.py "<job>" --capcut      # clips/*.mp4: drag into CapCut
```

Both flags can be combined. Then show the user the result: open the `clips` folder for CapCut, or
reveal `premiere.xml` (`open "<job>/clips"` / `open -R "<job>/premiere.xml"` on macOS, `explorer` on
Windows). For CapCut, mention once that each clip
starts up to a few seconds before its in-point (it has to start on a keyframe because nothing is
re-encoded), so they trim the head in CapCut. The Premiere timeline is frame-accurate and links to the
original source file, so that file must stay where it is.

## Notes

- When any step fails, look the symptom up in the table at the end of `SKILL_DIR/README.md`
  ("For Claude: when something goes wrong") before improvising.

- If the review page shows a black player, the browser cannot decode the source (ProRes, some HEVC).
  Say so and offer a one-time H.264 proxy of the source; do not silently encode.
- `python3 SKILL_DIR/scripts/test_clipper.py` checks the boundary and timecode logic.
