#!/usr/bin/env python3
"""
react_stack.py — CLI interface for React Stack.

Usage:
  python react_stack.py "https://youtube.com/shorts/VIDEO_ID"
  python react_stack.py "https://youtube.com/shorts/VIDEO_ID" --react storage/react.mp4 --out out/custom.mp4
  python react_stack.py "https://youtube.com/shorts/VIDEO_ID" --force third
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

# Ensure Python 3.14 user Scripts directory is on PATH for yt-dlp
_user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts"
if _user_scripts.exists():
    os.environ["PATH"] = str(_user_scripts) + os.pathsep + os.environ.get("PATH", "")

from pipeline import RESULT_PREFIX, run_pipeline

BASE = Path(__file__).resolve().parent
DEFAULT_REACT = BASE / "storage" / "react.mp4"
DEFAULT_OUT = BASE / "out"
DEFAULT_TMP = BASE / "tmp"


def main():
    parser = argparse.ArgumentParser(
        description="Stack a reaction clip on top of a YouTube Short."
    )
    parser.add_argument(
        "url",
        help="YouTube Shorts URL or local video path",
    )
    parser.add_argument(
        "--react",
        default=str(DEFAULT_REACT),
        help=f"Path to reaction clip MP4 (default: {DEFAULT_REACT})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output directory or specific output file path (default: out/)",
    )
    parser.add_argument(
        "--force",
        choices=["auto", "third", "half"],
        default="auto",
        help="Split mode override: auto (detect), third (640/1280), half (960/960)",
    )
    parser.add_argument(
        "--tmp",
        default=str(DEFAULT_TMP),
        help="Temporary directory for downloads and frames (default: tmp/)",
    )

    args = parser.parse_args()

    react_path = Path(args.react).resolve()
    if not react_path.exists():
        print(f"[error] Reaction clip not found: {react_path}")
        print("Please place your reaction clip at storage/react.mp4 or pass --react <path>")
        sys.exit(1)

    out_arg = Path(args.out).resolve()
    tmp_path = Path(args.tmp).resolve()
    tmp_path.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex[:8]

    if out_arg.suffix.lower() == ".mp4":
        out_dir = out_arg.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        # Target specific file path if passed
        target_out = out_arg
    else:
        out_dir = out_arg
        out_dir.mkdir(parents=True, exist_ok=True)
        target_out = out_dir / f"{job_id}.mp4"

    print(f"=== React Stack CLI ===")
    print(f"Input URL:    {args.url}")
    print(f"Reaction:     {react_path}")
    print(f"Output:       {target_out}")
    print(f"Split mode:   {args.force}")
    print("=" * 24)

    success = False
    result_data = {}

    try:
        for line in run_pipeline(
            url=args.url,
            react=react_path,
            out_dir=out_dir,
            tmp_dir=tmp_path,
            job_id=job_id,
            force=args.force,
        ):
            if line.startswith(RESULT_PREFIX):
                result_data = json.loads(line[len(RESULT_PREFIX):])
                success = result_data.get("success", False)
            else:
                print(line)

        # If user specified a custom .mp4 filename, rename generated output if needed
        generated = out_dir / f"{job_id}.mp4"
        if success and out_arg.suffix.lower() == ".mp4" and generated.exists() and generated != target_out:
            if target_out.exists():
                target_out.unlink()
            generated.rename(target_out)
            result_data["output"] = str(target_out)

    except KeyboardInterrupt:
        print("\n[interrupted] Operation cancelled by user.")
        sys.exit(130)
    except Exception as exc:
        print(f"\n[error] Unhandled error: {exc}")
        sys.exit(1)

    if success:
        print(f"\n[success] Video rendered: {result_data.get('output', target_out)}")
        sys.exit(0)
    else:
        print(f"\n[failed] Rendering failed: {result_data.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
