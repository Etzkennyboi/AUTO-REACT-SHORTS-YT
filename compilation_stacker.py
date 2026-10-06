#!/usr/bin/env python3
"""
compilation_stacker.py — Automated YouTube Compilation to 9:16 Shorts Generator.

Cuts funny clips out of long YouTube compilations (5-20 min),
strips sidebars/watermarks from the central funny clip,
and stacks your reaction video on top into vertical 1080x1920 Shorts.

Usage:
  # Scan compilation and list detected funny clips:
  python compilation_stacker.py "https://youtu.be/wfytNJTAZUA" --list

  # Render a single detected clip (e.g. Clip 4):
  python compilation_stacker.py "https://youtu.be/wfytNJTAZUA" --clip 4

  # Render a custom timestamp segment (e.g. 19.5s to 30.8s):
  python compilation_stacker.py "https://youtu.be/wfytNJTAZUA" --start 19.53 --end 30.77 --out out/short_custom.mp4

  # Batch render all detected clips:
  python compilation_stacker.py "https://youtu.be/wfytNJTAZUA" --batch --max-clips 10
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Ensure UTF-8 output encoding on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add user scripts to PATH
_user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts"
if _user_scripts.exists():
    os.environ["PATH"] = str(_user_scripts) + os.pathsep + os.environ.get("PATH", "")

BASE = Path(__file__).resolve().parent
DEFAULT_REACT = BASE / "storage" / "react.mp4"
DEFAULT_OUT = BASE / "out"
DEFAULT_TMP = BASE / "tmp"

DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
DEFAULT_TMP.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd: list[str]) -> str:
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd[:4])}...):\n{r.stderr[-1000:]}")
    return r.stdout


def download_compilation(url: str, tmp_dir: Path) -> Path:
    """Download video if not already present in tmp_dir."""
    if Path(url).exists() and Path(url).is_file():
        return Path(url).resolve()

    # Extract clean video ID or hash
    m = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url)
    vid_id = m.group(1) if m else "compilation"
    dest = tmp_dir / f"{vid_id}.mp4"

    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"[cache] Using already downloaded: {dest.name}")
        return dest

    print(f"[download] Fetching compilation: {url}")
    p314 = Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts" / "yt-dlp.exe"
    ytdlp = str(p314) if p314.exists() else (shutil.which("yt-dlp") or "yt-dlp")

    cmd = [
        ytdlp,
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "-o", str(dest),
        "--no-playlist",
        url,
    ]
    subprocess.run(cmd, check=True)
    return dest


def detect_scenes(video_path: Path, tmp_dir: Path, min_sec: float = 4.0, max_sec: float = 55.0) -> list[tuple[float, float, float]]:
    """
    Detect scene cut transitions using FFmpeg's scene filter.
    Returns list of (start_time, end_time, duration).
    """
    # Use relative path without colons or spaces for ffmpeg filter
    rel_scenes_file = f"tmp/{video_path.stem}_scenes.txt"
    if not Path(rel_scenes_file).exists():
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-filter:v", f"select='gt(scene,0.3)',metadata=print:file={rel_scenes_file}",
            "-f", "null", "-",
        ]
        subprocess.run(cmd, capture_output=True, check=True)

    cuts = [0.0]
    with open(rel_scenes_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "pts_time:" in line:
                try:
                    val = float(line.split("pts_time:")[1].strip())
                    if val - cuts[-1] >= min_sec:
                        cuts.append(round(val, 2))
                except ValueError:
                    continue

    # Get total video duration
    probe_raw = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(video_path)
    ])
    total_dur = float(json.loads(probe_raw)["format"]["duration"])
    if total_dur - cuts[-1] >= min_sec:
        cuts.append(round(total_dur, 2))

    clips = []
    for i in range(len(cuts) - 1):
        start = cuts[i]
        end = cuts[i + 1]
        dur = round(end - start, 2)
        if min_sec <= dur <= max_sec:
            clips.append((start, end, dur))

    return clips


def render_916_short(
    source_video: Path,
    react_video: Path,
    start_sec: float,
    dur_sec: float,
    out_file: Path,
    crop_filter: str = "crop=720:720:280:0",
    split_ratio: str = "third",  # "third" (640 react top, 1280 clip bot) or "half" (960/960)
) -> None:
    """Renders a vertical 9:16 Short (1080x1920) combining react.mp4 and compilation clip."""
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if split_ratio == "third":
        # React on top 1/3 (640px), Funny clip on bottom 2/3 (1280px)
        v_filter = (
            f"[0:v]scale=1138:640,crop=1080:640[react];"
            f"[1:v]{crop_filter},scale=1080:1280:force_original_aspect_ratio=increase,crop=1080:1280[clip];"
            f"[react][clip]vstack=inputs=2[v];"
            f"[0:a]volume=0.7[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first[a]"
        )
    else:
        # Half split (1080x960 each) - optimal for square-ish funny clips
        v_filter = (
            f"[0:v]scale=1706:960,crop=1080:960[react];"
            f"[1:v]{crop_filter},scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[clip];"
            f"[react][clip]vstack=inputs=2[v];"
            f"[0:a]volume=0.7[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first[a]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",  # loop reaction clip if duration exceeds reaction take
        "-i", str(react_video),
        "-ss", str(start_sec),
        "-t", str(dur_sec),
        "-i", str(source_video),
        "-filter_complex", v_filter,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(dur_sec),
        str(out_file),
    ]

    print(f"[render] Encoding {out_file.name} ({dur_sec:.1f}s)...")
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"[done] [OK] Successfully rendered: {out_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated compilation clipper and 9:16 reaction shorts generator."
    )
    parser.add_argument("url", help="YouTube compilation URL or local MP4 path")
    parser.add_argument("--react", default=str(DEFAULT_REACT), help="Path to reaction take (default: storage/react.mp4)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output folder or target .mp4 path")
    parser.add_argument("--list", action="store_true", help="List detected clips without rendering")
    parser.add_argument("--clip", type=int, help="Render a specific 1-based clip index from detected list")
    parser.add_argument("--start", type=float, help="Custom start timestamp (seconds)")
    parser.add_argument("--end", type=float, help="Custom end timestamp (seconds)")
    parser.add_argument("--batch", action="store_true", help="Batch render all detected clips")
    parser.add_argument("--max-clips", type=int, default=15, help="Maximum clips to render in batch mode (default: 15)")
    parser.add_argument("--split", choices=["third", "half"], default="third", help="Vertical split ratio (third: 640/1280, half: 960/960)")
    parser.add_argument("--crop", default="crop=720:720:280:0", help="FFmpeg crop filter to strip sidebars (default: crop=720:720:280:0)")

    args = parser.parse_args()

    react_path = Path(args.react).resolve()
    if not react_path.exists():
        print(f"[error] Reaction file not found at: {react_path}")
        print("Please place your reaction video in storage/react.mp4 or pass --react <path>")
        sys.exit(1)

    out_dir = Path(args.out).resolve()
    tmp_dir = DEFAULT_TMP

    # Step 1: Download or locate source video
    source_file = download_compilation(args.url, tmp_dir)

    # Step 2: Custom range mode
    if args.start is not None and args.end is not None:
        dur = args.end - args.start
        if dur <= 0:
            print("[error] --end must be greater than --start")
            sys.exit(1)
        out_name = out_dir if out_dir.suffix.lower() == ".mp4" else out_dir / f"short_{args.start:.1f}s_{args.end:.1f}s.mp4"
        render_916_short(source_file, react_path, args.start, dur, out_name, args.crop, args.split)
        return

    # Step 3: Detect scenes
    clips = detect_scenes(source_file, tmp_dir)
    print(f"\n[found] {len(clips)} funny clips detected in compilation:")
    for idx, (c_start, c_end, c_dur) in enumerate(clips, 1):
        print(f"  Clip {idx:02d}: {c_start:6.2f}s -> {c_end:6.2f}s  (duration: {c_dur:5.2f}s)")

    if args.list:
        return

    # Step 4: Render single clip by index
    if args.clip is not None:
        if args.clip < 1 or args.clip > len(clips):
            print(f"[error] Invalid clip index {args.clip}. Choose between 1 and {len(clips)}.")
            sys.exit(1)
        c_start, c_end, c_dur = clips[args.clip - 1]
        out_file = out_dir / f"short_clip{args.clip:02d}_{c_dur:.1f}s.mp4"
        render_916_short(source_file, react_path, c_start, c_dur, out_file, args.crop, args.split)
        return

    # Step 5: Batch render mode (Default behavior if no single clip specified)
    to_render = clips[:args.max_clips]
    print(f"\n[batch] Rendering {len(to_render)} Shorts with 1/3 react (640px) and 2/3 funny video (1280px)...")
    for idx, (c_start, c_end, c_dur) in enumerate(to_render, 1):
        out_file = out_dir / f"short_clip{idx:02d}_{c_dur:.1f}s.mp4"
        render_916_short(source_file, react_path, c_start, c_dur, out_file, args.crop, args.split)
    print(f"\n[success] All {len(to_render)} Shorts rendered to: {out_dir}")


if __name__ == "__main__":
    main()
