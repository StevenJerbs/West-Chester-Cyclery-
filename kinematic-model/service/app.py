"""harshmellow.ai rider-form service: one process serves humans and agents.

  GET  /                 human UI (upload, metadata, consent, results)
  POST /analyze          multipart video or JSON {url}, + metadata fields
                         -> {job_id}; analysis runs in a worker thread
  GET  /jobs/{id}        status + result document when done
  GET  /jobs/{id}/video  the labeled video (mp4)
  GET  /disciplines      envelope-backed disciplines
  /mcp                   MCP endpoint (streamable HTTP) exposing the same
                         capabilities as tools -- see mcp_server.py

Consent: a submission is kept for future training only when
consent_training=true; it is then copied to data/submissions/train/<job>/
with its metadata. Otherwise the source video is deleted after analysis
and only the result + labeled video remain under data/submissions/private/.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))  # so mcp_server imports under `uvicorn service.app:app`

from disciplines import DISCIPLINES  # noqa: E402

SUBMISSIONS = ROOT / "data" / "submissions"
(SUBMISSIONS / "train").mkdir(parents=True, exist_ok=True)
(SUBMISSIONS / "private").mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

# --- MCP: same capabilities for agents. Built before the FastAPI app so its
# session manager's lifespan can run inside ours (a mounted sub-app's own
# lifespan does not start automatically).
def _build_mcp_app():
    from mcp_server import mcp
    return mcp.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                   json_response=True)

try:
    _MCP_APP = _build_mcp_app()
except Exception as e:  # keep the human path alive even if MCP wiring fails
    print(f"[warn] MCP not mounted: {e}")
    _MCP_APP = None


@asynccontextmanager
async def _lifespan(app):
    if _MCP_APP is not None:
        async with _MCP_APP.router.lifespan_context(_MCP_APP):
            yield
    else:
        yield


app = FastAPI(title="harshmellow.ai rider form", version="1.0", lifespan=_lifespan)
if _MCP_APP is not None:
    app.mount("/mcp", _MCP_APP)


class Metadata(BaseModel):
    discipline: str = "downhill"
    terrain: str | None = None
    bike_model: str | None = None
    camera_view: str | None = None      # side | chase | pov | static | drone
    scene: str | None = None            # free text: where, conditions, what happened
    is_crash: bool = False
    is_race: bool = False
    rider_level: str | None = None      # beginner | intermediate | advanced | pro
    consent_training: bool = False
    consent_attribution: str | None = None  # how to credit, if at all


def _run_job(job_id: str, video: Path, meta: Metadata):
    from rider_model import RiderFormModel
    job_dir = video.parent
    try:
        JOBS[job_id]["status"] = "running"
        model = RiderFormModel()
        result = model.analyze(video, meta.discipline, out_dir=job_dir, metadata=meta.model_dump())
        JOBS[job_id].update(status="done", result=result,
                            labeled_video=result.get("labeled_video"))
        if meta.consent_training:
            dest = SUBMISSIONS / "train" / job_id
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(video, dest / video.name)
            (dest / "metadata.json").write_text(json.dumps(meta.model_dump(), indent=1))
            (dest / "result.json").write_text(json.dumps(result, indent=1))
        else:
            video.unlink(missing_ok=True)  # not consented: don't keep the source
    except Exception as e:  # surface, don't swallow
        JOBS[job_id].update(status="error", error=str(e))


def _download(url: str, dest_dir: Path) -> Path:
    import yt_dlp
    opts = {"format": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
            "outtmpl": str(dest_dir / "%(id)s.%(ext)s"), "quiet": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "static" / "index.html").read_text()


@app.get("/disciplines")
def disciplines():
    return {"disciplines": DISCIPLINES}


@app.post("/analyze")
async def analyze(video: UploadFile | None = File(None), url: str | None = Form(None),
                  discipline: str = Form("downhill"), terrain: str | None = Form(None),
                  bike_model: str | None = Form(None), camera_view: str | None = Form(None),
                  scene: str | None = Form(None), is_crash: bool = Form(False),
                  is_race: bool = Form(False), rider_level: str | None = Form(None),
                  consent_training: bool = Form(False),
                  consent_attribution: str | None = Form(None)):
    if video is None and not url:
        raise HTTPException(400, "provide a video file or a url")
    if discipline not in DISCIPLINES:
        raise HTTPException(400, f"discipline must be one of {DISCIPLINES}")
    meta = Metadata(discipline=discipline, terrain=terrain, bike_model=bike_model,
                    camera_view=camera_view, scene=scene, is_crash=is_crash,
                    is_race=is_race, rider_level=rider_level,
                    consent_training=consent_training, consent_attribution=consent_attribution)
    job_id = uuid.uuid4().hex[:12]
    job_dir = SUBMISSIONS / "private" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    if video is not None:
        suffix = Path(video.filename or "upload.mp4").suffix or ".mp4"
        path = job_dir / f"input{suffix}"
        with path.open("wb") as f:
            shutil.copyfileobj(video.file, f)
    else:
        try:
            path = _download(url, job_dir)
        except Exception as e:
            raise HTTPException(400, f"could not fetch url: {e}")
    with _LOCK:
        JOBS[job_id] = {"status": "queued", "metadata": meta.model_dump()}
    threading.Thread(target=_run_job, args=(job_id, path, meta), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return JSONResponse({k: v for k, v in j.items() if k != "labeled_video"} | {"job_id": job_id,
                        "video_url": f"/jobs/{job_id}/video" if j.get("labeled_video") else None})


@app.get("/jobs/{job_id}/video")
def job_video(job_id: str):
    j = JOBS.get(job_id)
    if not j or not j.get("labeled_video"):
        raise HTTPException(404, "no labeled video for this job (yet)")
    return FileResponse(j["labeled_video"], media_type="video/mp4", filename=f"{job_id}_labeled.mp4")


