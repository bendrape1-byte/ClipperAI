# Clipper

Clipper is a Claude Code skill. You give it a long video, it finds the parts worth cutting into shorts, and you get them back as a Premiere timeline or as files for CapCut. Everything runs on your own machine and you do not need any API keys.

## Install

You need Claude Code with a paid Claude plan, and access to this repo (ask Ben). Then paste this into Claude Code:

```
Install the Clipper skill from https://github.com/bendrape1-byte/ClipperAI and set it up for me.
```

Claude downloads the skill, checks your machine, tells you what it is about to install and installs it. All of it goes into the skill's own folder, so you do not need Homebrew or an admin password. The speech model is about 1.6 GB and downloads the first time you transcribe something.

## Use

Download the video the way you always do, with 4K Video Downloader, then drop the file into Claude Code and ask for clips. A YouTube link works too, but YouTube blocks outside downloaders every few weeks, so the file is the reliable route. If you know who is talking, say so. Whisper spells names better when it has seen them.

1. Claude transcribes the video. A 1h48m interview took 10.5 minutes on an Apple Silicon Mac with 24 GB.
2. Claude reads the transcript and picks the clips.
3. A review page opens in your browser. It plays each clip straight from the original file, so there is nothing to wait for.
4. Drag the two ends of the green bar under the player until the clip starts and ends cleanly, then approve it.
5. Press "Copy approved clips", paste the result into Claude and say whether you want Premiere or CapCut.

If you need the text, open Transcript under the trim bar. From there you can save the transcript of the clip you are on, or of the whole video, as a text file.

Keys on the review page: Space plays or pauses, the up and down arrows change clip, A approves, the left and right arrows move the in point, and Shift with the arrows moves the out point. Cmd+Z undoes a trim and Shift+Cmd+Z brings it back.

## What you get

For Premiere you get `premiere.xml`. Import it with File > Import and you have a sequence with every approved clip on it, cut to the frame and linked to the original video. Leave the original where it is or Premiere will ask you to relink it. Nobody has opened one of these in Premiere yet, so tell Ben how the first import goes.

For CapCut you get one video file per clip, copied out of the original without re-encoding. Each file starts a few seconds before your in point (4.8 seconds in our test) and ends half a second after your out point. Trim both ends in CapCut.

Everything for a video lands in `~/Movies/Clipper/<video name>/`.

## Known limits

- Whisper gets names and unusual words wrong. Tell Claude the names before it transcribes.
- The transcript has no speaker labels, so Claude sometimes has to guess who is talking.
- The review page cannot play ProRes and some HEVC files. Claude will tell you if that happens.
- So far it has run on Apple Silicon Macs only. Windows, Intel Macs and Macs with 8 GB are untested.

## For Claude: installing this skill

Follow this when a user asks you to install Clipper.

1. Clone into the user's skills folder: `git clone https://github.com/bendrape1-byte/ClipperAI ~/.claude/skills/clipper` (on Windows the folder is `%USERPROFILE%\.claude\skills\clipper`). If the folder already exists, run `git pull` inside it.
2. Read `SKILL.md` in that folder and do its step 0 (setup). Use `python` in place of `python3` on Windows.
3. Tell the user in one or two sentences what was installed, then ask for a video.

Say what you are doing before each step and run the commands yourself. The user is a video editor and may never have used a terminal.

## For Claude: when something goes wrong

Tell the user what happened in one plain sentence, then do the fix yourself where the table says you can.

| What you see | What to do |
|---|---|
| `git` or `python3` opens a macOS dialog about "command line developer tools", or prints `xcode-select` | Tell the user to click Install in that dialog and wait about five minutes, then run the command again. |
| `git` or `python` is missing on Windows | Run `winget install Git.Git` and `winget install Python.Python.3.12`, then open a new terminal. |
| The clone fails with "not found" or asks for a password | The repo is private. Run `gh auth login` if `gh` exists; otherwise tell the user to ask Ben for access to the repo with their GitHub account. |
| `pip install` fails | Read the error. With no network, say so. If the Python version is the problem, ask the user to install Python 3.12 from python.org, delete `.venv` in the skill folder and run setup again. |
| `setup.py --write` hangs or fails while fetching ffmpeg | It downloads about 80 MB from GitHub. Check the connection and run it again. |
| `/clipper` is not offered after installing | The skill list loads when a session starts. Follow `SKILL.md` directly in this session and tell the user it will appear next time. |
| Setup reports `"backend": "none"` | The machine is too weak to transcribe. The user needs an `.srt` file for each video from any transcription service; use `transcribe.py SOURCE --srt FILE`. |
| The model download stops or is slow | It is 1.6 GB and resumes. Run the transcription again. |
| Transcription crashes or the machine freezes | Not enough memory. Set `"model"` in `config.json` to `mlx-community/whisper-small-mlx` (Apple Silicon) or `small` (other machines) and run again. Tell the user the spelling will be a little worse. |
| The transcript is all lowercase with no punctuation | Whisper does this on some audio. Run the transcription again with `--prompt` set to one normal, punctuated sentence in the video's language, plus the speakers' names. |
| A YouTube link fails to download | The script has already updated the downloader and tried a second time. Do not debug further. Ask the user to download the video with 4K Video Downloader, then look for the file in `~/Movies/4K Video Downloader+/` or ask for its path. |
| `build_review.py` lists clips under `check` | The quotes did not match the transcript. Correct them in `candidates.json` as described in `SKILL.md` step 3 and run it again. Do not show the user a page with unchecked clips. |
| The review page shows a black player or no picture | The browser cannot decode the source. Try Chrome first. If it is ProRes or HEVC, ask whether to make a one-time H.264 copy of the source for previewing; do not encode without asking. |
| The player stays empty and the source was moved, renamed or sits on an unplugged drive | The page points at the original file's location. Have the user put the file back, or correct `source` in `job.json` and run `build_review.py` again. Approvals and trims are kept. |
| "Copy approved clips" does nothing | The page shows a text box with the same content at the bottom. Ask the user to copy that and paste it. |
| The user closed the page before copying | Open `review.html` again. Approvals and trims are saved in that browser. |
| CapCut refuses a clip or shows a frozen first second | Ask whether to re-encode that one clip, and only that one, then do it with ffmpeg. |
| A CapCut clip starts earlier than the chosen in point | Expected. The copy has to start on a keyframe. The user trims the head in CapCut. |
| Premiere shows the media as offline | The original file moved. Have the user relink it, or move it back. |
| Premiere places clips on the wrong frames | Do not guess. Collect the source file's frame rate and timecode with `ffprobe` and tell the user to send that to Ben. |
| The disk is full | Jobs live in `~/Movies/Clipper/`. Show the user the folder sizes and let them choose what to delete. Never delete a job or a source file yourself. |
