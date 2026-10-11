"""Check this machine and decide how transcription runs. Stdlib only.

python3 setup.py           -> print the plan as JSON (what is missing, what to install)
python3 setup.py --write   -> also save config.json once everything is installed
"""
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
WIN = platform.system() == "Windows"
VENV_PY = SKILL / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")


def ram_gb():
    if WIN:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "avail", "tp", "ap", "tv", "av", "ext")]
        m = MS()
        m.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 2**30
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30


def nvidia_vram_gb():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], text=True)
        return max(int(x) for x in out.split()) / 1024
    except Exception:
        return 0


def pick(ram, cores, vram, apple_silicon):
    # ponytail: thresholds are first guesses, not measured on agency machines.
    # Tune here, or override per machine by editing "model" in config.json.
    if apple_silicon:
        return {"backend": "mlx", "model": "mlx-community/whisper-large-v3-turbo", "pip": "mlx-whisper"}
    fw = {"backend": "faster-whisper", "pip": "faster-whisper"}
    if vram >= 4:
        return dict(fw, model="large-v3-turbo", device="cuda", compute_type="float16")
    cpu = dict(fw, device="cpu", compute_type="int8")
    if ram >= 16 and cores >= 8:
        return dict(cpu, model="large-v3-turbo")
    if ram >= 8:
        return dict(cpu, model="small")
    if ram >= 4:
        return dict(cpu, model="base")
    return {"backend": "none"}  # too weak: bring an .srt file instead


def main():
    ram, cores, vram = ram_gb(), os.cpu_count() or 1, nvidia_vram_gb()
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    cfg = pick(ram, cores, vram, apple)

    missing = [t for t in ("ffmpeg", "ffprobe", "yt-dlp") if not shutil.which(t)]
    commands = []
    if missing:
        pkgs = sorted({"ffmpeg" if t.startswith("ff") else t for t in missing})
        if platform.system() == "Darwin":
            commands.append("brew install " + " ".join(pkgs))
        elif WIN:
            commands += ["winget install %s" % {"ffmpeg": "Gyan.FFmpeg", "yt-dlp": "yt-dlp.yt-dlp"}[p] for p in pkgs]
        else:
            commands.append("sudo apt install -y " + " ".join(pkgs))

    whisper_ok = cfg["backend"] == "none"
    if not whisper_ok and VENV_PY.exists():
        mod = cfg["pip"].replace("-", "_")
        whisper_ok = subprocess.call([str(VENV_PY), "-c", "import " + mod],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    if not whisper_ok:
        if not VENV_PY.exists():
            commands.append('"%s" -m venv "%s"' % (sys.executable, SKILL / ".venv"))
        commands.append('"%s" -m pip install %s' % (VENV_PY, cfg["pip"]))

    ready = not commands
    plan = {
        "machine": {"os": platform.system(), "arch": platform.machine(), "ram_gb": round(ram, 1),
                    "cores": cores, "nvidia_vram_gb": round(vram, 1)},
        "config": dict(cfg, python=str(VENV_PY)),
        "missing_tools": missing,
        "commands": commands,
        "ready": ready,
        "note": ("The model itself (about 1.6 GB for large-v3-turbo, less for small/base) downloads on the first transcription."
                 if cfg["backend"] != "none" else
                 "This machine is too weak for local transcription. Use an .srt file: transcribe.py SOURCE --srt FILE"),
    }
    if "--write" in sys.argv and ready:
        (SKILL / "config.json").write_text(json.dumps(plan["config"], indent=2))
        plan["written"] = str(SKILL / "config.json")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
