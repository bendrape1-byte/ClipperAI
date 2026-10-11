"""Approved clips -> Premiere timeline (FCP7 XML) or lossless clip files for CapCut. Stdlib only.

python3 export.py JOB_DIR --premiere     writes JOB_DIR/premiere.xml (no encoding)
python3 export.py JOB_DIR --capcut       writes JOB_DIR/clips/*.mp4 (stream copy, no encoding)
Reads JOB_DIR/approved.json: {"clips": [{"title", "start", "end"}, ...]} (seconds in the source).
"""
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

from _tools import use_local_tools

use_local_tools()


def probe(src):
    d = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:format_tags=timecode:"
        "stream=codec_type,codec_name,r_frame_rate,width,height,channels,sample_rate:stream_tags=timecode",
        "-of", "json", str(src)]))
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    tc = next((s["tags"]["timecode"] for s in d["streams"] if s.get("tags", {}).get("timecode")),
              d["format"].get("tags", {}).get("timecode"))
    return v, a, float(d["format"]["duration"]), tc


def rate_xml(fps):
    # xmeml stores 29.97/59.94 as timebase 30/60 + ntsc TRUE
    return "<rate><timebase>%d</timebase><ntsc>%s</ntsc></rate>" % (
        round(fps), "TRUE" if fps.denominator == 1001 else "FALSE")


def tc_to_frames(tc, fps):
    base = round(fps)
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    n = ((h * 60 + m) * 60 + s) * base + f
    if ";" in tc:  # drop-frame: 2 frame numbers (4 at 59.94) skipped each minute except every 10th
        mins = h * 60 + m
        n -= (base // 15) * (mins - mins // 10)
    return n


def premiere_xml(src, clips):
    v, a, duration, tc = probe(src)
    fps = Fraction(v["r_frame_rate"])
    rate = rate_xml(fps)
    to_f = lambda sec: round(Fraction(str(sec)) * fps)
    total = to_f(duration)
    url = src.as_uri().replace("file:///", "file://localhost/", 1)
    channels = int(a["channels"]) if a else 0

    audio = ("<audio><samplecharacteristics><depth>16</depth><samplerate>%s</samplerate></samplecharacteristics>"
             "<channelcount>%d</channelcount></audio>" % (a["sample_rate"], channels)) if a else ""
    file_full = (
        '<file id="src"><name>%s</name><pathurl>%s</pathurl>%s<duration>%d</duration>'
        '<timecode>%s<string>%s</string><frame>%d</frame><displayformat>%s</displayformat></timecode>'
        '<media><video><samplecharacteristics>%s<width>%s</width><height>%s</height></samplecharacteristics></video>'
        '%s</media></file>'
    ) % (escape(src.name), url, rate, total, rate, tc or "00:00:00:00", tc_to_frames(tc, fps) if tc else 0,
         "DF" if tc and ";" in tc else "NDF", rate, v["width"], v["height"], audio)

    vitems, aitems, pos = [], [[] for _ in range(channels)], 0
    for i, c in enumerate(clips, 1):
        fin, fout = to_f(c["start"]), min(to_f(c["end"]), total)
        n = fout - fin
        links = ('<link><linkclipref>v%d</linkclipref><mediatype>video</mediatype>'
                 '<trackindex>1</trackindex><clipindex>%d</clipindex></link>' % (i, i))
        for ch in range(1, channels + 1):
            links += ('<link><linkclipref>a%d_%d</linkclipref><mediatype>audio</mediatype>'
                      '<trackindex>%d</trackindex><clipindex>%d</clipindex></link>' % (i, ch, ch, i))
        common = ('<name>%s</name><enabled>TRUE</enabled><duration>%d</duration>%s'
                  '<start>%d</start><end>%d</end><in>%d</in><out>%d</out>') % (
            escape(c["title"]), total, rate, pos, pos + n, fin, fout)
        vitems.append('<clipitem id="v%d">%s%s%s</clipitem>' % (i, common, file_full if i == 1 else '<file id="src"/>', links))
        for ch in range(1, channels + 1):
            aitems[ch - 1].append(
                '<clipitem id="a%d_%d">%s<file id="src"/><sourcetrack><mediatype>audio</mediatype>'
                '<trackindex>%d</trackindex></sourcetrack>%s</clipitem>' % (i, ch, common, ch, links))
        pos += n

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="seq">'
        '<name>%s</name><duration>%d</duration>%s'
        '<timecode>%s<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
        '<media><video><format><samplecharacteristics>%s<width>%s</width><height>%s</height>'
        '<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>'
        '<track>%s</track></video><audio>%s</audio></media></sequence></xmeml>\n'
    ) % (escape("Clips - " + src.stem), pos, rate, rate, rate, v["width"], v["height"],
         "".join(vitems), "".join("<track>%s</track>" % "".join(t) for t in aitems))


TAIL_PAD_SEC = 0.5  # editors trim in CapCut: a clip may run long, never short


def capcut_clips(src, clips, out_dir):
    """Stream copy: no encoding. Each clip starts on the keyframe at or before its
    in-point and runs TAIL_PAD_SEC past its out-point, so it is never too short."""
    _, a, _, _ = probe(src)
    # uncompressed camera audio is safer in .mov than in .mp4
    ext = ".mov" if a and a["codec_name"].startswith("pcm") else src.suffix.lower() or ".mp4"
    out_dir.mkdir(exist_ok=True)
    written = []
    for i, c in enumerate(clips, 1):
        name = re.sub(r"[^\w\- ]", "", c["title"]).strip()[:60] or "clip"
        out = out_dir / ("%02d %s%s" % (i, name, ext))
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % c["start"], "-to", "%.3f" % (c["end"] + TAIL_PAD_SEC), "-i", str(src),
               "-map", "0:v:0", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        subprocess.check_call(cmd[:-4] + (["-map", "0:a:0"] if a else []) + cmd[-4:] + [str(out)])
        written.append(str(out))
    return written


def main():
    job = Path(sys.argv[1]).expanduser().resolve()
    src = Path(json.loads((job / "job.json").read_text())["source"])
    clips = json.loads((job / "approved.json").read_text())["clips"]
    if not clips:
        sys.exit("no approved clips")
    result = {}
    if "--premiere" in sys.argv:
        (job / "premiere.xml").write_text(premiere_xml(src, clips), encoding="utf-8")
        result["premiere"] = str(job / "premiere.xml")
    if "--capcut" in sys.argv:
        result["capcut"] = capcut_clips(src, clips, job / "clips")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
