# harshmellow.ai · Rider Form service

One process, two front doors:

| Door | Path | Who |
|---|---|---|
| Web UI | `GET /` | riders and coaches: upload or link, tag the scene, opt in to training, get a grade + labeled video |
| REST | `POST /analyze`, `GET /jobs/{id}`, `GET /jobs/{id}/video` | apps and scripts |
| MCP | `/mcp` (streamable HTTP) or `python service/mcp_server.py` (stdio) | agents: `analyze_video`, `get_analysis`, `list_disciplines`, `describe_model` |

## Run locally

```bash
cd kinematic-model
pip install -r requirements.txt -r service/requirements.txt
uvicorn service.app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. First run downloads the base YOLO weights; fine-tuned
checkpoints in `weights/` are picked up automatically (latest `kinematic_pose_v*.pt`).

## Deploy (Docker)

```bash
cd kinematic-model
docker build -f service/Dockerfile -t harshmellow-rider-form .
docker run -p 8000:8000 -v $(pwd)/data/submissions:/app/data/submissions harshmellow-rider-form
```

Put it behind your TLS terminator for harshmellow.ai and point the domain at port 8000.
The `data/submissions` volume is where consented training footage accumulates.

A GPU is not required; CPU inference runs a 10 s clip in ~2–4 min. For production
throughput, run several replicas or add a queue in front of `/analyze` — the job
model in `app.py` is a single-process thread pool by design, to keep the first
deployment simple.

## Agent access (MCP)

Streamable HTTP endpoint: `https://harshmellow.ai/mcp`. Example with the MCP Python SDK:

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
async with streamablehttp_client("https://harshmellow.ai/mcp") as (r, w, _):
    async with ClientSession(r, w) as s:
        await s.initialize()
        res = await s.call_tool("analyze_video", {"path_or_url": "https://youtu.be/...",
                                                  "discipline": "enduro",
                                                  "consent_training": False})
```

Set `MCP_ALLOWED_HOSTS` handling / `transport_security` in `app.py` if you serve MCP
from a hostname other than the one requests arrive on (DNS-rebinding protection in the SDK).

## Consent and data

- `consent_training=false` (default): the source video is deleted after analysis; the
  result JSON and labeled video stay under `data/submissions/private/<job>/`.
- `consent_training=true`: source + metadata + result are copied to
  `data/submissions/train/<job>/`. Discipline, terrain, bike, camera view, crash and race
  flags, and self-reported rider level become training labels for the next model round.
- Withdrawal: delete `data/submissions/train/<job>/` by job id.

## What the result contains

`form.grade` (0–100 vs the discipline envelope; `envelope_source` says whether that
band was learned from advanced riders or is the coaching prior), `form.deviations`
(timestamped "not on par" windows, also drawn on the labeled video), `cornering`
(turns with lean, smoothness, gaze lead, counter-rotation, exit-speed ratio),
`attitude` (monocular pitch/lean/yaw proxies), `fatigue` (within-run drift),
`crash_risk` (when a control model is trained), `factor_report` (what separates
advanced riders — populated only once enough labeled runs exist).
