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
