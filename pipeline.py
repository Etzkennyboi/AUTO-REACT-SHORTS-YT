#!/usr/bin/env python3
"""
pipeline.py — Core React Stack processing engine.

Generator-based pipeline: yields log strings consumed by the FastAPI SSE stream.
Final yield is a __RESULT__ JSON sentinel consumed by the worker thread.

Layout rules (from PRD):
  - Real 9:16  → react top 1/3 (640px), short bottom 2/3 (1280px)
  - 16:9 file, or 16:9-in-9:16 with blur bars → equal split (960 / 960), bars cropped

Needs: ffmpeg, ffprobe on PATH; pillow, numpy installed.
"""

import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Generator, Optional, Tuple

import numpy as np
from PIL import Image

OUT_W, OUT_H = 1080, 1920
RESULT_PREFIX = "__RESULT__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ytdlp_cmd() -> list[str]:
    """Find the best yt-dlp executable, favoring the updated Python 3.14 install."""
    p314 = Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts" / "yt-dlp.exe"
    exe = str(p314) if p314.exists() else (shutil.which("yt-dlp") or "yt-dlp")
    cmd = [exe]
    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])
    return cmd


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:14]


def _run(cmd: list[str]) -> str:
    """Run command, raise RuntimeError on failure, return stdout."""
    r = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return r.stdout


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------

def probe(path: Path) -> dict:
    raw = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    data = json.loads(raw)
    stream = data["streams"][0]
    dur = float(stream.get("duration") or data["format"]["duration"])
    return {"width": int(stream["width"]), "height": int(stream["height"]), "duration": dur}


def grab_frame(path: Path, dest: Path) -> None:
    _run(["ffmpeg", "-y", "-ss", "1", "-i", str(path), "-frames:v", "1", str(dest)])


# ---------------------------------------------------------------------------
# Layout detection
# ---------------------------------------------------------------------------

def _blur_bars(frame_path: Path) -> Tuple[bool, Optional[tuple]]:
    """Detect if a vertical frame is a 16:9 picture padded with blur bars."""
    im = np.asarray(Image.open(frame_path).convert("L"), dtype=np.float32)
    h, w = im.shape
    if h <= w:
        return False, None

    def detail(band: np.ndarray) -> float:
        return float(
            np.mean(np.abs(np.diff(band, axis=0)))
            + np.mean(np.abs(np.diff(band, axis=1)))
        )

    top = detail(im[: h // 5])
    mid = detail(im[h // 3: 2 * h // 3])
    bot = detail(im[-h // 5:])
    padded = mid > 1.8 * ((top + bot) / 2) and mid > 4.0

    band_h = int(round(w * 9 / 16))
    y = max(0, (h - band_h) // 2)
    return padded, (0, y, w, band_h)


def classify(w: int, h: int, frame_path: Path) -> Tuple[str, Optional[tuple]]:
    """Return (mode, crop) where mode is 'equal' or 'third'."""
    if w / h >= 1.2:
        return "equal", None
    padded, band = _blur_bars(frame_path)
    if padded:
        return "equal", band
    return "third", None


# ---------------------------------------------------------------------------
# ffmpeg encode (streaming progress)
# ---------------------------------------------------------------------------

def encode(
    react: Path,
    short: Path,
    out: Path,
    mode: str,
    duration: float,
    crop: Optional[tuple],
) -> Generator[str, None, None]:
    """Yields progress log strings. Raises RuntimeError on failure."""
    rh = OUT_H // 2 if mode == "equal" else OUT_H // 3
    sh = OUT_H - rh

    short_chain = "[1:v]setpts=PTS-STARTPTS"
    if crop:
        x, y, cw, ch = crop
        short_chain += f",crop={cw}:{ch}:{x}:{y}"
    short_chain += (
        f",scale={OUT_W}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{sh},setsar=1[bot]"
    )

    filt = (
        f"[0:v]scale={OUT_W}:{rh}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{rh},setsar=1,trim=duration={duration},setpts=PTS-STARTPTS[top];"
        f"{short_chain};"
        f"[top][bot]vstack=inputs=2[v];"
        f"[0:a]atrim=duration={duration},asetpts=PTS-STARTPTS,volume=1.3[ra];"
        f"[1:a]volume=0.35[sa];"
        f"[ra][sa]amix=inputs=2:duration=first:dropout_transition=0[a]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(react),
        "-i", str(short),
        "-filter_complex", filt,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(out),
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # Drain stderr in background so it never blocks stdout
    stderr_buf: list[str] = []
    def _drain():
        for ln in proc.stderr:
            stderr_buf.append(ln)
    threading.Thread(target=_drain, daemon=True).start()

    for raw in proc.stdout:
        raw = raw.strip()
        if raw.startswith("out_time_ms="):
            try:
                ms = int(raw.split("=")[1])
                t = ms / 1_000_000
                pct = min(99, int(t / duration * 100))
                yield f"[encode] {t:.1f}s / {duration:.1f}s ({pct}%)"
            except (ValueError, ZeroDivisionError):
                pass
        elif raw == "progress=end":
            yield "[encode] Finalizing..."

    proc.wait()
    if proc.returncode != 0:
        tail = "".join(stderr_buf)[-1500:]
        raise RuntimeError(f"ffmpeg exited {proc.returncode}:\n{tail}")

    yield "[encode] Done ✓"


# ---------------------------------------------------------------------------
# Main pipeline generator
# ---------------------------------------------------------------------------

def run_pipeline(
    url: str,
    react_path: str | Path,
    out_dir: str | Path,
    tmp_dir: str | Path,
    job_id: str,
    force: str = "auto",
) -> Generator[str, None, None]:
    """
    Generator that yields log strings.
    The final yield is a line starting with RESULT_PREFIX followed by JSON.
    The caller (worker thread) must detect and parse that line.
    """
    out_dir = Path(out_dir)
    tmp_dir = Path(tmp_dir)
    react = Path(react_path)
    out = out_dir / f"{job_id}.mp4"

    # --- validate react ---
    if not react.exists():
        yield f"[error] Reaction clip not found: {react}"
        yield f"{RESULT_PREFIX}{json.dumps({'success': False, 'error': f'React not found: {react}'})}"
        return

    yield f"[info] Reaction clip: {react.name} ✓"

    # --- download (cached by URL hash) ---
    h = url_hash(url)
    short = tmp_dir / f"{h}.mp4"
    frame = tmp_dir / f"{h}_frame.png"

    if short.exists():
        yield f"[download] Cache hit → {short.name}"
    else:
        yield "[download] Starting download..."
        cmd = [
            "yt-dlp", "-f", "bv*[height<=1080]+ba/b",
            "--merge-output-format", "mp4",
            "--newline",
            "-o", str(short), url,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for ln in proc.stdout:
            ln = ln.strip()
            if ln:
                yield f"[download] {ln}"
        proc.wait()
        if proc.returncode != 0:
            yield "[error] yt-dlp download failed — check the URL and try again"
            yield f"{RESULT_PREFIX}{json.dumps({'success': False, 'error': 'Download failed'})}"
            return
        yield "[download] Complete ✓"

    # --- probe ---
    yield "[probe] Reading video metadata..."
    try:
        info = probe(short)
    except Exception as exc:
        yield f"[error] Probe failed: {exc}"
        yield f"{RESULT_PREFIX}{json.dumps({'success': False, 'error': str(exc)})}"
        return

    w, h_px, dur = info["width"], info["height"], info["duration"]
    yield f"[probe] {w}×{h_px}, {dur:.2f}s"

    # --- frame grab + classify ---
    if not frame.exists():
        yield "[classify] Extracting frame..."
        try:
            grab_frame(short, frame)
        except Exception as exc:
            yield f"[classify] Frame grab skipped ({exc})"

    if force != "auto":
        mode = force
        crop = None
        yield f"[classify] Forced → {mode}"
    else:
        yield "[classify] Detecting layout..."
        try:
            mode, crop = classify(w, h_px, frame)
        except Exception as exc:
            yield f"[classify] Detection error ({exc}), defaulting to third"
            mode, crop = "third", None
        note = " (blur bars cropped)" if crop else ""
        yield f"[classify] Mode: {mode}{note}"

    # --- encode ---
    yield f"[encode] Starting → {out.name}"
    try:
        for line in encode(react, short, out, mode, dur, crop):
            yield line
    except Exception as exc:
        yield f"[error] Encode failed: {exc}"
        yield f"{RESULT_PREFIX}{json.dumps({'success': False, 'error': str(exc)})}"
        return

    yield f"[done] ✓ {out.name} — {dur:.1f}s, {mode} split"
    yield f"{RESULT_PREFIX}{json.dumps({'success': True, 'output': str(out), 'mode': mode, 'duration': dur})}"
