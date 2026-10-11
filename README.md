# Clipper

Clipper is a Claude Code skill. You give it a long video, it finds the parts worth cutting into shorts, and you get them back as a Premiere timeline or as files for CapCut. Everything runs on your own machine and you do not need any API keys.

## Install

Clone the repo into your Claude skills folder:

```bash
git clone <repo-url> ~/.claude/skills/clipper
```

Then open Claude Code and type `set up clipper`. Claude looks at your machine, tells you what it is about to install (ffmpeg, yt-dlp and Whisper) and installs it. The speech model is about 1.6 GB and downloads the first time you transcribe something.

## Use

Drop a video file or a YouTube link into Claude Code and ask for clips. If you know who is talking, say so. Whisper spells names better when it has seen them.

1. Claude transcribes the video. A 1h48m interview took 10.5 minutes on an Apple Silicon Mac with 24 GB.
2. Claude reads the transcript and picks the clips.
3. A review page opens in your browser. It plays each clip straight from the original file, so there is nothing to wait for.
4. Drag the two ends of the green bar under the player until the clip starts and ends cleanly, then approve it. The page shows the words the clip now starts and ends on while you drag.
5. Press "Copy approved clips", paste the result into Claude and say whether you want Premiere or CapCut.

Keys on the review page: Space plays or pauses, the up and down arrows change clip, A approves, the left and right arrows move the in point, and Shift with the arrows moves the out point. Cmd+Z undoes a trim and Shift+Cmd+Z brings it back.

## What you get

For Premiere you get `premiere.xml`. Import it with File > Import and you have a sequence with every approved clip on it, cut to the frame and linked to the original video. Leave the original where it is or Premiere will ask you to relink it. Nobody has opened one of these in Premiere yet, so tell Ben how the first import goes.

For CapCut you get one video file per clip, copied out of the original without re-encoding. Each file starts a few seconds before your in point (4.8 seconds in our test) and ends half a second after your out point. Trim both ends in CapCut.

Everything for a video lands in `~/Movies/Clipper/<video name>/`.

## Known limits

- Whisper gets names and unusual words wrong. Tell Claude the names before it transcribes.
- The transcript has no speaker labels, so Claude sometimes has to guess who is talking.
- The review page cannot play ProRes and some HEVC files. Claude will tell you if that happens.
- So far it has run on one Mac. Windows and smaller Macs are untested.
