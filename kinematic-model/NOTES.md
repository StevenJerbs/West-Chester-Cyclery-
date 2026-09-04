# Handoff notes (cloud session -> local GPU session)

State as of the last cloud push on `claude/downhill-bike-kinematic-training-105gzd`.
Everything committed lives in `src/`, `data/*.yaml`, `crash_training/` and the
READMEs. The items below are gitignored artefacts that were generated in the
cloud container and must be regenerated locally.

## Generated artefacts (not in git)

| Path | What | Size | Regenerate with |
|---|---|---|---|
| `weights/control_model_v001.joblib` | crash/control logistic model, 144 windows, 23 videos, LOO AUC 0.719 | ~10 KB | `crash_model.train(datasets)` over the 20 Friday Fails candidate tracks + 3 clean runs, labels from `data/crashes.yaml` (see commit "Label Friday Fails crash moments") |
| `weights/kinematic_pose_v001..003.pt` | pose fine-tunes from earlier sessions | n/a | `train_pose.py` (earlier sessions); base `yolov8n-pose.pt` works if absent |
| `data/raw/goldstone/vds_2023.mp4`, `msa_2023.mp4` | H.264 transcodes of the AV1 FPV clips (OpenCV cannot decode AV1) | 54 MB, 115 MB | `ffmpeg -i crash_training/<file> -an -c:v libx264 -crf 18 -pix_fmt yuv420p <out>` (use imageio_ffmpeg's binary, it has dav1d) |
| `data/raw/asa_vs_charlie/s{1,2,3}_{asa,charlie}.mp4` | the 6 single-rider cuts | 7-15 MB each | cut from `asa_vermette_vs_avg_rider_Y50K3ZZEdVY.mp4` at the `asa_range` / `charlie_range` in `crash_training/Y50K3ZZEdVY.segments.json` |
| `data/raw/friday_fails_720p.mp4`, `output/friday2/candidates/*.mp4` | 720p transcode and 20 x 10 s candidate clips | 656 MB / small | `long_video.find_candidate_clips(n=20, clip_len_s=10, min_gap_s=45)` on the Friday Fails source |
| `output/**/track.json, result.json, labeled.mp4` | all per-run outputs | varies | `RiderFormModel().analyze(video, "downhill", out_dir=..., metadata={...})` |
| `weights/tire_model_v*.json` | tyre grip envelope | none written | `tire_model.fit_envelope(...)` refused: no run yet passes the slip self-check |

## Where things stand

- Wheel / suspension / tyre layer (`wheels.py`, `tire_model.py`, `kinematics.py`) is
  wired into `RiderFormModel.analyze()` and the labeled video. On FPV chase
  footage it measures wheels, roll, contact, rotation rates and a speed
  estimate; it self-reports travel as saturated and slip as unmeasurable.
  Sharper, closer footage (trackside 120 fps or on-bike wheel cam) is what
  would let `fit_envelope` learn a real envelope.
- `detect_orientation` now needs a rotation to clearly beat upright; metadata
  `rotate_deg` overrides it. The MSA clip was previously processed upside down.
- Detection retries at 1280 px, then on a zoomed crop around the rider
  (`BikeRiderTracker._roi_detect`); segmentation does the same.
- Asa vs Charlie: 6 clips tracked, both riders labeled in `data/riders.yaml`,
  `form_grade.factor_report()` is live (advanced vs other).
- Goldstone: both FPV runs tracked and labeled; numbers in `data/videos.yaml`.

## Not done / ideas for the GPU session

- Re-run the 7 confirmed Friday Fails crash clips through the wheel/tyre layer
  so `fit_envelope` has pre-crash wheel frames (they were tracked before the
  layer existed).
- `crash_model` does not yet use tyre features; add them only once crash
  footage carries them too, or the classifier learns "has tyre data = safe".
- Quarter-view front/rear wheel labels can still swap; rear views are solid.
- Fork/shock travel needs a closer camera to leave the saturation cap.
