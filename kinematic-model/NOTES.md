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

## Regenerated locally on the GPU session (2026-09-03, RTX 3070)

All gitignored artefacts above now exist on the PC (`C:\Users\nadc7\Videos\West-Chester-Cyclery-`), produced with the
mtbkin venv (`C:\Users\nadc7\my-project\.venv`, torch 2.3.1+cu121, ultralytics 8.4, scikit-learn 1.9, imageio-ffmpeg 0.6).

| Artefact | How | Time |
|---|---|---|
| `data/raw/goldstone/{vds,msa}_2023.mp4`, `data/raw/asa_vs_charlie/s{1,2,3}_{asa,charlie}.mp4` | ffmpeg with NVIDIA hardware decode (`-hwaccel cuda`) + `h264_nvenc` cq 19 | 15 s for all 8 |
| `output/friday2/candidates/cand_*.mp4` + `candidates_manifest.json` | `long_video.find_candidate_clips(n=20, clip_len_s=10, min_gap_s=45)`; reproduced all 20 clip names exactly, so `data/crashes.yaml` labels apply unchanged | 64 s |
| `output/friday2/candidates/<cand>/track.json` (20) | `track.track_video(rotate_deg=0)` on GPU | 16-20 s per 10 s clip |
| `output/goldstone/*`, `output/asa_vs_charlie/*` (8 full `RiderFormModel.analyze` runs) | GPU | 25-60 s per short clip, 161 s (vds) / 207 s (msa) |
| `weights/control_model_v001.joblib` | `crash_model.train()` over 20 candidates + 8 clean runs | seconds |

Control model report (local): 372 windows, 349 positive, 23 negative, 28 videos, LOO AUC 0.625. The cloud v001 was
144 windows / 23 videos / LOO AUC 0.719. The local run used 8 clean runs (both Goldstone clips and all six Asa/Charlie
cuts) instead of 3, and GPU tracking with the zoomed retry yields more windows passing the 30% pose-coverage filter.
With only 23 pre-crash windows the AUC is noisy either way; treat neither number as a benchmark until more crash footage
carries windows.

Pose inference with `kinematic_pose_v003.pt` at 640 px: ~22 ms/frame on the GPU vs ~250 ms on CPU on this machine.


## Bike + rider labeling rework (2026-09-04, GPU session)

`track.py` now runs the mtbkin DH bike keypoint model (`weights/bikekp_v4_fullframe.pt`, YOLOv8s-pose @1024,
class `bike`, keypoints front_axle / rear_axle / fork_crown / bottom_bracket; trained on 666 labeled DH frames in
the mtbkin project) as the primary bike detector, with the COCO `bicycle` class as fallback. Both weights files are
gitignored (`*.pt`); copy `bikekp_v4_fullframe.pt` and `bikekp_v4_crop.pt` from `C:/Users/nadc7/my-project/data/models/`
into `weights/`. Without them the tracker silently runs COCO-only as before.

What changed per frame:
- bike: DH model full-frame -> COCO 640/1280 -> zoomed retry (crop model + COCO) around the rider or the last box.
- rider: full-frame pose -> zoomed retry around the bike (or last hips). Skeletons must be articulated
  (>=5 joints, mean conf >=0.45; >=7 / 0.5 when nothing anchors the choice); with a confident bike the rider's
  hips must lie within 1.5 bike sizes of it.
- acceptance: a bike box stands alone only if conf >=0.5 AND its own keypoints look like a bike (>=2 confident,
  axles inside the lower 70% of the box). Anything weaker needs a credible rider standing on it (hips/ankles over
  the box) or continuity with the tracked bike, and continuity expires 15 frames after the last rider-supported
  box so one false box cannot carry itself. Zoomed-retry hits never stand alone (upscaled crops inflate conf).
- new FrameTrack fields: `bike_kps`, `bike_source` (bikekp | coco | bikekp_roi | coco_roi), `pose_source` (full | roi).
- `wheels.find_wheels(..., bike_kps=)`: confident model axles decide front/rear and stand in for a wheel no ellipse
  fits (flagged `approx` + `from_axle`; excluded from the mm/px scale). `labeled.py` draws the four bike points.

Frame-weighted coverage on a fixed 12-clip set (2 Goldstone drone, 6 Asa/Charlie trackside, 4 Friday Fails
compilation clips; `output/_eval_v2/metrics_*.json`, baseline = the cloud session's track.json files):

| pass | what | drone (Goldstone x2) pose / bike | trackside (Asa/Charlie x6) pose / bike | compilation (Friday Fails x4) pose / bike | all pose / bike |
|---|---|---|---|---|---|
| baseline | COCO bicycle + yolov8n-pose, ROI retry for bike only | 0.79 / 0.36 | 0.95 / 0.54 | 0.35 / 0.22 | 0.71 / 0.37 |
| v2 | bikekp-first + ROI retries, no gates | 0.83 / 0.89 | 0.96 / 0.89 | 0.40 / 0.74 | 0.75 / 0.85 |
| v3 | + size plausibility / skeleton credibility gates | 0.84 / 0.79 | 0.96 / 0.83 | 0.40 / 0.68 | 0.75 / 0.77 |
| v4 | + rider-support or continuity for weak boxes | 0.86 / 0.77 | 0.97 / 0.82 | 0.42 / 0.61 | 0.77 / 0.74 |
| v5 | + retry never alone, continuity expires, tighter support | 0.85 / 0.72 | 0.97 / 0.81 | 0.42 / 0.53 | 0.77 / 0.69 |
| v6 | + keypoint-plausibility gate, articulated skeleton for support | 0.86 / 0.68 | 0.97 / 0.80 | 0.42 / 0.41 | 0.77 / 0.64 |

Precision check: for each pass, 24 frames the new tracker labeled that the baseline missed were eyeballed
(`prec_v*/sheet.jpg`). Roughly 10/24 correct at v3, 15/24 at v6. The remaining false positives are almost all
helmet-cam frames inside the Friday Fails clips (no third-person bike exists there) and bystanders at start/finish;
drone and trackside gains are correct in nearly every sampled frame. Coverage on the compilation clips is therefore
the number to distrust, not the drone/trackside ones.

Wheel layer on two full `RiderFormModel.analyze` runs: both-wheel coverage s1_charlie 0.39 -> 0.61, s3_asa
0.43 -> 0.71 (23% of frames use an axle-placed wheel); form grades unchanged. Axle jitter rose 17 -> 26 px and
23 -> 32 px because more hard frames are covered and model axles jitter more than ellipse fits. Next step for that
is the per-shot temporal tracking mtbkin uses (CoTracker/LK + 3-frame median), not more gating.

Speed on the RTX 3070 with all retries: 10-20 fps at 1080p (three models, up to five passes on a bad frame).


### Outputs regenerated with the new tracker (2026-09-04)

All 20 Friday Fails candidate tracks and the 8 clean runs were re-run (`output/`), the previous outputs moved to
`output/_baseline_cloudtracker/`. Per-run coverage, old -> new (pose / bike / both wheels), form grade in brackets:

| run | pose | bike | both wheels | form |
|---|---|---|---|---|
| goldstone/vds_2023 | 0.75 -> 0.84 | 0.36 -> 0.66 | 0.26 -> 0.47 | 43.3 -> 45.2 |
| goldstone/msa_2023 | 0.82 -> 0.88 | 0.36 -> 0.70 | 0.30 -> 0.64 | 58.2 -> 58.0 |
| asa_vs_charlie/s1_asa | 0.99 -> 0.99 | 0.65 -> 0.76 | 0.65 -> 0.74 | 33.6 -> 33.6 |
| asa_vs_charlie/s1_charlie | 1.00 -> 1.00 | 0.44 -> 0.67 | 0.39 -> 0.61 | 31.0 -> 31.0 |
| asa_vs_charlie/s2_asa | 0.87 -> 0.95 | 0.51 -> 0.85 | 0.50 -> 0.84 | 38.7 -> 41.1 |
| asa_vs_charlie/s2_charlie | 0.93 -> 0.97 | 0.61 -> 0.90 | 0.49 -> 0.85 | 29.2 -> 30.0 |
| asa_vs_charlie/s3_asa | 0.85 -> 0.87 | 0.46 -> 0.85 | 0.43 -> 0.71 | 47.8 -> 47.7 |
| asa_vs_charlie/s3_charlie | 0.96 -> 1.00 | 0.69 -> 0.93 | 0.66 -> 0.89 | 43.0 -> 44.6 |

Full `RiderFormModel.analyze` on the GPU now takes 36-91 s per Asa/Charlie clip, 198 s (vds) and 440 s (msa).

**Crash classifier: the LOO AUC cannot be trusted at this data scale, for either tracker.** Retrained on the new
tracks: 427 windows, 30 negatives, LOO AUC 0.469 (old tracks: 372 / 23 / 0.625). Ablation showed the AUC is
averaged over only 1 (old) or 2 (new) held-out videos: a fold counts only if the held-out clip has both classes,
and most crash clips have too few windows with >=30% pose coverage in the 4 s lead-in to contribute a negative.
Removing the two coverage features drops the old tracker's number to 0.5; the coverage features alone score below
0.25 on both. So the earlier 0.72 / 0.63 figures were single-fold noise, not evidence of a working risk model.
Nothing about the new tracker made the classifier worse; it needs more crash clips with a tracked lead-in (the
Windrock crashes at 2549 s, 2831 s and 3620 s are the obvious next additions) and a proper grouped CV report
that states the number of folds. `weights/control_model_v001.joblib` is now the new-tracker fit; the old one is
`output/_baseline_cloudtracker/control_model_v001.joblib`.

Because the regen script analyses clean runs before training, `output/goldstone/msa_2023/result.json` says
crash risk unavailable; re-run `analyze` after training when a risk read-out is wanted on that run.
