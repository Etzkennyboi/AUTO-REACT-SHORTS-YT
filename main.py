"""
main.py — FastAPI server for React Stack.

Endpoints:
  GET  /                       Serves ui/index.html
  GET  /api/react-status       Whether storage/react.mp4 exists
  POST /api/run                Start a new job  { url, force?, react? }
  GET  /api/stream/{job_id}    SSE log stream
  GET  /api/jobs               List all jobs (newest first)
  GET  /api/download/{job_id}  Download rendered mp4
  DELETE /api/jobs/{job_id}    Delete job + output file

Run: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

# Ensure the latest yt-dlp (user-installed for Python 3.14) is on PATH
_user_scripts = Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts"
if _user_scripts.exists():
    os.environ["PATH"] = str(_user_scripts) + os.pathsep + os.environ.get("PATH", "")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import RESULT_PREFIX, run_pipeline

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE = Path(__file__).parent
OUT_DIR = BASE / "out"
TMP_DIR = BASE / "tmp"
UI_DIR = BASE / "ui"
STORAGE_DIR = BASE / "storage"
REACT_DEFAULT = STORAGE_DIR / "react.mp4"

OUT_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)
STORAGE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="React Stack")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------
jobs: dict[str, dict] = {}


def make_job(job_id: str, url: str, force: str) -> dict:
    return {
        "id": job_id,
        "url": url,
        "force": force,
        "status": "running",   # running | done | error
        "output": None,
        "error": None,
        "created": time.time(),
        "logs": [],            # all log lines (for late-joining SSE clients)
        "done_event": threading.Event(),
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    url: str
    react: Optional[str] = None
    force: str = "auto"


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/react-status")
def react_status():
    p = REACT_DEFAULT
    if p.exists():
        mb = p.stat().st_size / 1_048_576
        return {"found": True, "size": f"{mb:.1f} MB", "path": str(p)}
    return {"found": False, "path": str(p)}


@app.post("/api/run")
def start_run(req: RunRequest):
    job_id = uuid.uuid4().hex[:8]
    react = Path(req.react) if req.react else REACT_DEFAULT
    job = make_job(job_id, req.url, req.force)
    jobs[job_id] = job

    def worker():
        try:
            for line in run_pipeline(req.url, react, OUT_DIR, TMP_DIR, job_id, req.force):
                if line.startswith(RESULT_PREFIX):
                    result = json.loads(line[len(RESULT_PREFIX):])
                    if result.get("success"):
                        job["status"] = "done"
                        job["output"] = result.get("output")
                    else:
                        job["status"] = "error"
                        job["error"] = result.get("error", "Unknown error")
                else:
                    job["logs"].append(line)
        except Exception as exc:
            job["logs"].append(f"[error] Unhandled: {exc}")
            job["status"] = "error"
            job["error"] = str(exc)
        finally:
            if job["status"] == "running":
                job["status"] = "error"
                job["error"] = "Pipeline ended unexpectedly"
            job["done_event"].set()

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
def stream_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]

    def generate():
        cursor = 0
        while True:
            # Drain any new log lines
            logs = job["logs"]
            while cursor < len(logs):
                yield f"data: {json.dumps({'line': logs[cursor]})}\n\n"
                cursor += 1

            if job["done_event"].is_set():
                # Final drain (logs added just before event set)
                logs = job["logs"]
                while cursor < len(logs):
                    yield f"data: {json.dumps({'line': logs[cursor]})}\n\n"
                    cursor += 1
                payload = {"status": job["status"], "job_id": job_id, "output": job["output"]}
                yield f"event: done\ndata: {json.dumps(payload)}\n\n"
                break

            # Wait up to 0.4s for new logs, then send keepalive
            job["done_event"].wait(timeout=0.4)
            yield ": keepalive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs")
def list_jobs():
    return [
        {
            "id": j["id"],
            "url": j["url"],
            "status": j["status"],
            "output": j["output"],
            "error": j["error"],
            "created": j["created"],
        }
        for j in sorted(jobs.values(), key=lambda x: x["created"], reverse=True)
    ]


@app.get("/api/download/{job_id}")
def download_job(job_id: str):
    job = jobs.get(job_id)
    if not job or not job["output"]:
        raise HTTPException(404, "Output not ready")
    p = Path(job["output"])
    if not p.exists():
        raise HTTPException(404, "File missing from disk")
    return FileResponse(p, media_type="video/mp4", filename=p.name)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.pop(job_id, None)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["output"]:
        p = Path(job["output"])
        if p.exists():
            p.unlink(missing_ok=True)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Static UI — mount LAST so API routes take priority
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
