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
→ suspension activity → segmentation → wheels (axles, fork/shock travel,
wheel roll, ground contact) → tyre model (slip, camber, grip envelope) → bike
attitude proxies → cornering → discipline-aware form grade with timestamped
deviations → fatigue drift → crash risk → factor report → labeled video.

| Layer | Module | Status |
|---|---|---|
| Detection + pose | `track.py`: DH bike model `weights/bikekp_v4_fullframe.pt` (box + axle/crown/BB keypoints, COCO fallback) + rider pose `weights/kinematic_pose_v*.pt`, zoomed retries for both | bike coverage 0.37 -> 0.64, pose 0.71 -> 0.77 on the 12-clip eval set (NOTES.md) |
| Suspension / terrain roughness | `suspension.py` | rule-based, validated |
| Joint angles + vision path | `joint_analysis.py` | validated on 3 runs |
| Silhouette outlines | `outline.py` | YOLOv8-seg |
| Bike attitude (pitch / lean / yaw) | `attitude.py` | monocular proxies |
| Wheels: axles, fork/shock travel, wheel roll, contact, deflection | `wheels.py` + `data/bike_specs.yaml` | mm scale from wheel diameter; travel is sprung-vs-unsprung distance change; contact is heuristic |
| Bike keypoints over time + keypoint travel | `bike_kp_track.py` (LK-prior refinement of the 4 DH bike points), `wheels.kp_travel_series` | jitter -25-40%; fork travel from crown-to-axle length on side-view frames only, rear unmeasurable at this resolution (NOTES.md) |
| Tyre: slip ratio, slip angle, camber, grip envelope, traction-loss events | `tire_model.py` | Magic-Formula (Pacejka) envelope, rally-sim loose-surface defaults, refit from corpus via `fit_envelope()`; slip needs a sharp, oblique wheel |
| Cornering | `cornering.py` | metrics only; no verdicts until labeled data |
| Discipline envelopes (12) | `disciplines.py` | coaching priors; learned bands after ≥3 advanced runs |
| Form grade, deviations, fatigue, factors | `form_grade.py` | grades against envelope; factor report live (Asa vs Charlie, Goldstone) |
| Crash risk | `crash_model.py` + `data/crashes.yaml` | control_model_v001: 7 verified Friday Fails crashes, LOO AUC 0.72 |
| Long-video funnel | `long_video.py` | validated on a 92-min source |
| Service: web UI, REST, MCP | `service/` | see `service/README.md` |

Data registries: `data/videos.yaml` (sources processed), `data/riders.yaml`
(rider + run labels incl. level and discipline), `data/crashes.yaml` (crash
moments), `data/sources.yaml` (footage sources by discipline with licensing
status). Consented uploads land in `data/submissions/train/`.

Honest limits: attitude and speed are 2D proxies; cornering and fatigue are
descriptive until enough labeled runs exist to learn what separates advanced
riders; crash risk is trained on 7 crashes. The wheel/tyre layer measures
what a single camera can see: wheel ellipses give roll and the mm scale,
axle-to-bar / axle-to-pedal distances give travel, and slip needs the wheel
seen obliquely with sharp ground under it -- on blurred FPV chase footage it
reports "unmeasurable" rather than a number. Tyre sidewall deformation is
below pixel resolution and is not reported. Each result document says which
of these apply.
