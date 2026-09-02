# Downhill Bike Kinematic Visual Model

Pipeline that tracks bike and rider geometry in downhill footage, scores
suspension activity, exports annotated highlight shots, and continues
training the pose model on each new video.

## Quick start

```bash
cd kinematic-model
pip install -r requirements.txt
python src/pipeline.py https://youtu.be/u2gOY98G0B8
```

Note: run this from a machine with YouTube access. Managed remote sessions
may block youtube.com at the network level; in that case download the video
elsewhere and pass the local file path instead of the URL.

## What it does

1. **Track** (`track.py`) — YOLOv8 detection finds the bicycle, YOLOv8-pose
   finds the rider's 17-keypoint skeleton. Per frame it derives hip, knee,
   and elbow angles, the bike box, and rider center-of-mass offset.
2. **Score** (`suspension.py`) — flags windows where suspension is cycling
   in rough terrain: high-frequency vertical bike chatter (with the slow
   camera motion removed), fast knee/elbow angle changes as the rider
   absorbs hits, and bike-box "breathing" as a travel proxy.
3. **Highlights** (`highlights.py`) — exports the top-scoring windows as
   annotated MP4 clips plus a peak-frame PNG still each: skeleton overlay,
   bike box, live joint angles, and a suspension-activity meter.
4. **Continue training** (`finetune.py`) — converts high-confidence frames
   into YOLO-pose labels and fine-tunes from the latest checkpoint in
   `weights/` (`kinematic_pose_vNNN.pt`), so every processed video advances
   the model instead of restarting it.

## Training set

`data/videos.yaml` is the manifest of videos the model trains on. Update a
video's `status` to `processed` after tracking and `trained` after
fine-tuning completes.

## Outputs

```
output/<video_id>/
  track.json         per-frame geometry
  suspension.json    activity score over time
  highlights/        highlight_NN_*.mp4 / *_peak.png + highlights.json
```

## Merged model (rider-form-1.0) and the harshmellow.ai service

Everything above is now one model. `src/rider_model.py::RiderFormModel.analyze()`
runs: orientation detect → track (bike box + 17-kp pose + joint angles + gaze)
→ suspension activity → segmentation → bike attitude proxies → cornering →
discipline-aware form grade with timestamped deviations → fatigue drift →
crash risk (once a control model exists) → factor report → labeled video.

| Layer | Module | Status |
|---|---|---|
| Detection + pose | `track.py`, checkpoints `weights/kinematic_pose_v*.pt` | trained, v003 |
| Suspension / terrain roughness | `suspension.py` | rule-based, validated |
| Joint angles + vision path | `joint_analysis.py` | validated on 3 runs |
| Silhouette outlines | `outline.py` | YOLOv8-seg |
| Bike attitude (pitch / lean / yaw) | `attitude.py` | monocular proxies |
| Cornering | `cornering.py` | metrics only; no verdicts until labeled data |
| Discipline envelopes (12) | `disciplines.py` | coaching priors; learned bands after ≥3 advanced runs |
| Form grade, deviations, fatigue, factors | `form_grade.py` | grades against envelope; factor report needs ≥3 runs per level |
| Crash risk | `crash_model.py` + `data/crashes.yaml` | built, untrained (no crash footage yet) |
| Long-video funnel | `long_video.py` | validated on a 92-min source |
| Service: web UI, REST, MCP | `service/` | see `service/README.md` |

Data registries: `data/videos.yaml` (sources processed), `data/riders.yaml`
(rider + run labels incl. level and discipline), `data/crashes.yaml` (crash
moments), `data/sources.yaml` (footage sources by discipline with licensing
status). Consented uploads land in `data/submissions/train/`.

Honest limits: attitude and speed are 2D proxies; cornering and fatigue are
descriptive until enough labeled runs exist to learn what separates advanced
riders; crash risk needs crash-labeled footage. Each result document says
which of these apply.
