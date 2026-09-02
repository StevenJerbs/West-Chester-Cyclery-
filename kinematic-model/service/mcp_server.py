"""MCP server for the rider-form model -- agent-native access to the same
analysis humans get through the web form.

Tools:
  analyze_video(path_or_url, discipline, ...metadata..., consent_training)
      Runs the merged model and returns the result document; the labeled
      video path is included so a client can fetch it.
  get_analysis(job_id)
      Result document for a prior job (server-mode).
  list_disciplines()
      Disciplines with form envelopes.
  describe_model()
      What the model measures, what is a proxy, what needs more data.

Consent semantics are identical to the HTTP path: nothing is retained for
training unless consent_training=true.

Run standalone (stdio) for local agents:  python mcp_server.py
Mounted at /mcp (streamable HTTP) by app.py for remote agents.
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

from mcp.server.mcpserver import MCPServer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

mcp = MCPServer("harshmellow-rider-form")
SUBMISSIONS = ROOT / "data" / "submissions"


@mcp.tool()
def list_disciplines() -> list[str]:
    """Disciplines the form grader has envelopes for."""
    from disciplines import DISCIPLINES
    return DISCIPLINES


@mcp.tool()
def describe_model() -> dict:
    """What the merged rider-form model measures and its current limits."""
    from disciplines import COACHING
    return {
        "measures": ["bike + rider detection and 17-keypoint pose", "joint angles: hip, knee, ankle, "
                     "shoulder, elbow, wrist, neck, torso", "vision path (head-orientation sightline)",
                     "suspension activity / terrain roughness", "bike attitude proxies: pitch, lean, yaw",
                     "cornering: turn detection, lean smoothness, gaze lead, counter-rotation, exit speed ratio",
                     "form grade vs discipline envelope with timestamped deviations",
                     "fatigue drift within a run", "crash risk (when a control model is trained)"],
        "proxies": "attitude and speed are monocular 2D proxies, not IMU/GPS values",
        "needs_more_data": ["crash risk model (needs crash-labeled footage)",
                            "learned advanced-rider envelopes per discipline (>=3 advanced runs each)",
                            "factor report on what separates advanced riders (>=3 runs per level)"],
        "disciplines": list(COACHING),
    }


@mcp.tool()
def analyze_video(path_or_url: str, discipline: str = "downhill", terrain: str | None = None,
                  bike_model: str | None = None, camera_view: str | None = None,
                  scene: str | None = None, is_crash: bool = False, is_race: bool = False,
                  rider_level: str | None = None, consent_training: bool = False,
                  render_video: bool = True) -> dict:
    """Analyze a riding video (local path or URL). Returns the full result
    document (grade, deviations, cornering, attitude, fatigue, crash risk)
    and the path of the labeled video. The source is kept for training only
    if consent_training is true."""
    from rider_model import RiderFormModel
    job_id = uuid.uuid4().hex[:12]
    job_dir = SUBMISSIONS / "private" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    src = Path(path_or_url)
    if path_or_url.startswith("http"):
        import yt_dlp
        opts = {"format": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
                "outtmpl": str(job_dir / "%(id)s.%(ext)s"), "quiet": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(path_or_url, download=True)
            src = Path(ydl.prepare_filename(info))
    elif not src.exists():
        return {"error": f"no such file: {path_or_url}"}
    else:
        dst = job_dir / src.name
        shutil.copy2(src, dst)
        src = dst
    meta = {"discipline": discipline, "terrain": terrain, "bike_model": bike_model,
            "camera_view": camera_view, "scene": scene, "is_crash": is_crash,
            "is_race": is_race, "rider_level": rider_level, "consent_training": consent_training}
    result = RiderFormModel().analyze(src, discipline, out_dir=job_dir, metadata=meta,
                                      render_video=render_video)
    result["job_id"] = job_id
    if consent_training:
        keep = SUBMISSIONS / "train" / job_id
        keep.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, keep / src.name)
        (keep / "metadata.json").write_text(json.dumps(meta, indent=1))
        (keep / "result.json").write_text(json.dumps(result, indent=1))
    else:
        src.unlink(missing_ok=True)
    return result


@mcp.tool()
def get_analysis(job_id: str) -> dict:
    """Result document for a prior job id."""
    for sub in ("private", "train"):
        p = SUBMISSIONS / sub / job_id / "result.json"
        if p.exists():
            return json.loads(p.read_text())
    return {"error": "unknown job"}


if __name__ == "__main__":
    mcp.run("stdio")  # stdio transport for local agents
