"""RiderFormModel -- the merged bike + rider kinematics model.

One entry point, `analyze(video, discipline, ...)`, that runs every layer
built so far in order and returns a single result document plus a
labeled video:

  1. orientation detect + track      (track.py)      bike box, 17-kp pose,
                                                     joint angles, gaze
  2. suspension activity             (suspension.py) rough-terrain score
  3. joint-angle time series         (joint_analysis.py)
  4. segmentation masks              (outline.py)    bike/rider silhouettes
  5. bike attitude proxies           (attitude.py)   pitch / lean / yaw
  6. cornering                       (cornering.py)  turns + per-turn metrics
  7. form grade vs discipline band   (form_grade.py) grade, deviations,
                                                     fatigue, crash risk
  8. factor report                   (form_grade.py) what separates advanced
                                                     riders, when data allows
  9. labeled video                                   overlays + deviation flags

Long inputs (> LONG_VIDEO_S) go through the long_video funnel first and
the best verified candidate window is analyzed, so a 90-minute upload
returns a result instead of timing out.

Checkpoint used: latest weights/kinematic_pose_v*.pt for pose if present,
else the base yolov8n-pose.pt. Everything in the result is tagged with
which checkpoint and which envelope source produced it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
LONG_VIDEO_S = 90.0
MODEL_VERSION = "rider-form-1.0"


def _latest_pose_ckpt() -> str:
    w = sorted((ROOT / "weights").glob("kinematic_pose_v*.pt"))
    return str(w[-1]) if w else "yolov8n-pose.pt"


def _duration_s(video: Path) -> float:
    cap = cv2.VideoCapture(str(video))
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return float(n / fps) if n > 0 else 0.0


def _to_h264(src: Path, dst: Path):
    import imageio_ffmpeg, subprocess
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264",
                    "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
                   check=True)


class RiderFormModel:
    def __init__(self, with_segmentation: bool = True):
        self.with_segmentation = with_segmentation
        self.pose_ckpt = _latest_pose_ckpt()

    # ------------------------------------------------------------------
    def analyze(self, video: str | Path, discipline: str = "downhill",
                out_dir: str | Path | None = None, metadata: dict | None = None,
                render_video: bool = True) -> dict:
        video = Path(video)
        out_dir = Path(out_dir) if out_dir else ROOT / "output" / "service" / video.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        dur = _duration_s(video)
        source_note = None
        if dur > LONG_VIDEO_S:
            video, source_note = self._pick_window_from_long(video, out_dir)

        from track import BikeRiderTracker, detect_orientation, track_video
        from suspension import suspension_score
        from joint_analysis import analyze as joint_analyze
        from form_grade import grade_run, fatigue_index, crash_risk, factor_report
        from cornering import analyze_cornering
        from attitude import attitude_series

        tracker = BikeRiderTracker(pose_weights=self.pose_ckpt)
        rot = (metadata or {}).get("rotate_deg")
        rot = int(rot) if rot is not None else detect_orientation(video, tracker)
        track_json = out_dir / "track.json"
        track_video(video, track_json, rotate_deg=rot)
        track = json.loads(track_json.read_text())
        fps = track["fps"]

        sus_times, sus_scores = suspension_score(track_json, out_dir / "suspension.json")
        analysis = joint_analyze(track_json, out_dir / "analysis.json")

        from wheels import wheel_series, load_bike_specs
        from tire_model import tire_summary, load_envelope

        masks = self._segment(video, track, rot, fps) if self.with_segmentation else None
        attitude_series(track["frames"], masks)
        specs = load_bike_specs((metadata or {}).get("bike_id"))
        wheels_summary = wheel_series(track["frames"], fps, specs)
        tire_env = load_envelope()
        tire = tire_summary(track["frames"], fps, tire_env)
        from kinematics import rotation_rates, speed_series
        from track import _ROTATIONS
        rates = rotation_rates(track["frames"], fps)
        speed = speed_series(video, track["frames"], _ROTATIONS.get(rot % 360), fps)
        track_json.write_text(json.dumps(track))

        cornering = analyze_cornering(track["frames"], fps)
        grading = grade_run(analysis, discipline)
        fatigue = fatigue_index(analysis)
        risk = crash_risk(track_json)
        factors = factor_report()

        att = [f.get("attitude", {}) for f in track["frames"]]
        def _stat(key):
            v = [a[key] for a in att if a.get(key) is not None]
            return {"mean": round(float(np.mean(v)), 1), "max_abs": round(float(np.max(np.abs(v))), 1),
                    "coverage": round(len(v) / max(len(att), 1), 2)} if v else None
        views = [a.get("view") for a in att if a.get("view") and a.get("view") != "unknown"]
        attitude_summary = {
            "pitch_deg": _stat("pitch_deg"), "lean_deg": _stat("lean_deg"),
            "torso_tilt_deg": _stat("torso_tilt_deg"),
            "dominant_view": max(set(views), key=views.count) if views else "unknown",
            "note": "monocular proxies -- see attitude.py; not IMU-grade yaw/pitch/roll",
        }

        pose_cov = float(np.mean([len(f.get("keypoints", {})) >= 6 for f in track["frames"]])) if track["frames"] else 0.0
        bike_cov = float(np.mean([f.get("bike_box") is not None for f in track["frames"]])) if track["frames"] else 0.0

        result = {
            "model_version": MODEL_VERSION,
            "pose_checkpoint": Path(self.pose_ckpt).name,
            "video": video.name, "duration_s": round(_duration_s(video), 2),
            "source_note": source_note, "rotation_applied_deg": rot,
            "discipline": discipline, "metadata": metadata or {},
            "tracking": {"pose_coverage": round(pose_cov, 2), "bike_coverage": round(bike_cov, 2),
                         "frames": len(track["frames"]), "fps": round(fps, 2)},
            "suspension": {"mean": round(float(sus_scores.mean()), 3) if len(sus_scores) else None,
                           "peak": round(float(sus_scores.max()), 3) if len(sus_scores) else None,
                           "peak_at_s": round(float(sus_times[int(np.argmax(sus_scores))]), 2) if len(sus_scores) else None},
            "form": grading,
            "attack_position_pct": round(100 * (analysis.get("attack_score_mean") or 0), 1),
            "lookahead_pct": analysis.get("gaze_lookahead_pct"),
            "attitude": attitude_summary,
            "wheels": wheels_summary,
            "tire": tire,
            "rotation_rates": rates,
            "speed": speed,
            "bike_specs": {k: specs.get(k) for k in ("wheel_front_in", "wheel_rear_in", "fork_travel_mm",
                                                     "rear_travel_mm", "tire_pressure_front_psi",
                                                     "tire_pressure_rear_psi", "source")},
            "cornering": cornering,
            "fatigue": fatigue,
            "crash_risk": risk,
            "factor_report": factors,
            "elapsed_s": round(time.time() - t0, 1),
        }
        if render_video:
            raw = out_dir / "labeled_raw.mp4"
            self._render_labeled(video, track, rot, sus_times, sus_scores, grading, cornering, raw)
            final = out_dir / "labeled.mp4"
            _to_h264(raw, final)
            raw.unlink(missing_ok=True)
            result["labeled_video"] = str(final)
        (out_dir / "result.json").write_text(json.dumps(result, indent=1))
        result["result_path"] = str(out_dir / "result.json")
        return result

    # ------------------------------------------------------------------
    def _pick_window_from_long(self, video: Path, out_dir: Path):
        """Funnel a long video to its best verified riding window."""
        from long_video import find_candidate_clips
        from track import BikeRiderTracker, detect_orientation, track_video
        cands = find_candidate_clips(video, out_dir / "candidates", n=8, clip_len_s=12)
        best, best_score = None, -1.0
        tracker = BikeRiderTracker(pose_weights=self.pose_ckpt)
        for c in cands:
            clip = Path(c["clip"])
            rot = detect_orientation(clip, tracker)
            recs = track_video(clip, out_dir / "candidates" / f"{clip.stem}_track.json",
                               rotate_deg=rot, max_frames=int(12 * 30))
            if not recs:
                continue
            bike = np.mean([r.bike_box is not None for r in recs])
            pose = np.mean([len(r.keypoints) >= 6 for r in recs])
            score = 0.6 * bike + 0.4 * pose
            if bike > 0.15 and score > best_score:
                best, best_score = clip, score
        if best is None:
            raise RuntimeError("no window with a tracked bike + rider found in this long video")
        return best, f"long input ({_duration_s(video):.0f}s); analyzed best verified window {best.name}"

    def _segment(self, video: Path, track: dict, rot: int, fps: float = 30.0) -> dict[int, np.ndarray]:
        """Segmentation pass, and -- since it already walks every frame with
        the bike mask in hand -- the wheel / contact / tyre pass too. Each
        tracked frame gains `wheels`, `contact` and `tire` records."""
        from outline import OutlineTracker
        from track import _ROTATIONS
        from wheels import find_wheels, contact_score
        from tire_model import tire_state_for_wheel, load_envelope
        seg = OutlineTracker()
        env = load_envelope()
        code = _ROTATIONS.get(rot % 360)
        by_idx = {f["frame"]: f for f in track["frames"]}
        cap = cv2.VideoCapture(str(video))
        masks, i = {}, 0
        prev_gray, prev_wheels, plane = None, None, (1.0, 0.0)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if code is not None:
                frame = cv2.rotate(frame, code)
            rec = by_idx.get(i)
            near, roi = None, None
            if rec and rec.get("bike_box"):
                x1, y1, x2, y2 = rec["bike_box"]
                near = ((x1 + x2) / 2, (y1 + y2) / 2)
                roi = 3.0 * max(y2 - y1, x2 - x1, 60.0)
            bike_mask, _ = seg.masks_for_frame(frame, near_point=near, roi_size=roi)
            if bike_mask is not None:
                masks[i] = bike_mask
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if rec is not None:
                wh = find_wheels(frame, bike_mask, rec.get("bike_box"), rec.get("keypoints", {}), prev=prev_wheels,
                                 bike_kps=rec.get("bike_kps"))
                F, R = wh.get("front"), wh.get("rear")
                if F and R:
                    dx, dy = F["cx"] - R["cx"], F["cy"] - R["cy"]
                    n = max(np.hypot(dx, dy), 1e-6)
                    plane = (dx / n, dy / n)
                rec["wheels"] = {"front": F, "rear": R, "method": wh["method"]}
                rec["contact"], rec["tire"] = {}, {}
                for side in ("front", "rear"):
                    w = wh.get(side)
                    if not w:
                        continue
                    pw = (prev_wheels or {}).get(side)
                    av = (w["cx"] - pw["cx"], w["cy"] - pw["cy"]) if pw else None
                    rec["contact"][side] = contact_score(gray, prev_gray, w, av)
                    rec["tire"][side] = tire_state_for_wheel(prev_gray, gray, w, pw, plane, "auto", env, fps)
                prev_wheels = wh
            prev_gray = gray
            i += 1
        cap.release()
        return masks

    def _draw_hud(self, frame, rec, w, t):
        """Top-right panel: live pitch/roll/yaw rate with running maxima, and
        the ground-speed estimate. Maxima accumulate as the video plays so a
        viewer sees the peak rotation rate build through the run."""
        if not hasattr(self, "_hud_max"):
            self._hud_max = {"pitch": 0.0, "roll": 0.0, "yaw": 0.0}
        rates = (rec or {}).get("rates") or {}
        x0, y0 = w - 330, 20
        cv2.rectangle(frame, (x0 - 10, y0 - 14), (w - 10, y0 + 118), (0, 0, 0), -1)
        cv2.putText(frame, "rotation rate  (proxy, deg/s)   now    max", (x0, y0 + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        y = y0 + 28
        for k, label in (("pitch", "pitch"), ("roll", "roll"), ("yaw", "yaw")):
            v = rates.get(f"{k}_rate_deg_s")
            if v is not None:
                self._hud_max[k] = max(self._hud_max[k], abs(v))
            now = f"{v:+6.0f}" if v is not None else "   --"
            cv2.putText(frame, f"{label:<6}{now:>22}   {self._hud_max[k]:4.0f}", (x0, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            y += 22
        sp = (rec or {}).get("speed_kmh_smooth")
        cv2.putText(frame, f"speed est  {sp:5.1f} km/h" if sp is not None else "speed est   -- km/h", (x0, y + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 220, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "ground-flow estimate, not GPS", (x0, y + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160), 1, cv2.LINE_AA)

    def _render_labeled(self, video, track, rot, sus_times, sus_scores, grading, cornering, out_path):
        self._hud_max = {"pitch": 0.0, "roll": 0.0, "yaw": 0.0}
        from highlights import annotate, _frame_lookup, _score_at
        from track import _ROTATIONS
        code = _ROTATIONS.get(rot % 360)
        lookup = _frame_lookup(track)
        fps = track["fps"]
        devs = grading.get("deviations", [])
        turns = cornering.get("turns", [])
        cap = cv2.VideoCapture(str(video))
        writer, i = None, 0
        RED, AMBER = (60, 60, 230), (40, 180, 240)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if code is not None:
                frame = cv2.rotate(frame, code)
            t = i / fps
            rec = lookup.get(i)
            annotate(frame, rec, _score_at(sus_times, sus_scores, t))
            if rec:
                from wheels import draw_wheels
                draw_wheels(frame, rec)
            h, w = frame.shape[:2]
            self._draw_hud(frame, rec, w, i / fps)
            # deviation flags: the "not on par" highlights
            y = h - 60
            for d in devs:
                if d["start_s"] <= t <= d["end_s"]:
                    msg = f"{d['joint'].replace('_angle','').upper()} {d['side']} band by {d['severity_deg']:.0f} deg  -  {d['cue']}"
                    cv2.rectangle(frame, (w - 20 - 11 * len(msg), y - 22), (w - 10, y + 6), (0, 0, 0), -1)
                    cv2.putText(frame, msg, (w - 15 - 11 * len(msg), y), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, RED, 2, cv2.LINE_AA)
                    y -= 30
            for k, tr in enumerate(turns):
                if tr["start_s"] <= t <= tr["end_s"]:
                    cv2.putText(frame, f"turn {k+1} {tr['direction']}  lean {tr['peak_lean_deg']} deg  smooth {tr['lean_smoothness']}",
                                (10, h - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, AMBER, 2, cv2.LINE_AA)
            att = (rec or {}).get("attitude") or {}
            if att.get("view") != "unknown":
                cv2.putText(frame, f"view {att.get('view')}  pitch {att.get('pitch_deg')}  lean {att.get('lean_deg')} (proxy)",
                            (10, 24 + 22 * 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
            if grading.get("grade") is not None:
                cv2.putText(frame, f"form grade {grading['grade']:.0f}/100  ({grading['discipline']}, {grading['envelope_source']} band)",
                            (w // 2 - 260, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            if writer is None:
                writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            writer.write(frame)
            i += 1
        if writer:
            writer.release()
        cap.release()


if __name__ == "__main__":
    import sys
    vid = sys.argv[1]
    disc = sys.argv[2] if len(sys.argv) > 2 else "downhill"
    r = RiderFormModel().analyze(vid, disc)
    print(json.dumps({k: r[k] for k in ("form", "attitude", "cornering", "fatigue", "crash_risk", "elapsed_s")}, indent=1)[:3000])
