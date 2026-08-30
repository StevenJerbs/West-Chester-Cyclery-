"""Highlight-shot export.

Given tracking records and picked windows, renders annotated clips (MP4)
and stills (PNG) showing the model tracking bike and rider geometry:
skeleton overlay, bike box, joint angles, and a live suspension-activity
meter. Stills are taken at each window's peak-score frame.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from track import SKELETON_EDGES

GREEN = (80, 220, 80)
CYAN = (255, 220, 60)
ORANGE = (40, 140, 255)
WHITE = (240, 240, 240)


def _frame_lookup(track_data: dict) -> dict[int, dict]:
    return {f["frame"]: f for f in track_data["frames"]}


def _score_at(times: np.ndarray, scores: np.ndarray, t: float) -> float:
    if len(times) == 0:
        return 0.0
    return float(np.interp(t, times, scores))


def annotate(frame, rec: dict | None, score: float):
    h, w = frame.shape[:2]
    if rec:
        if rec.get("bike_box"):
            x1, y1, x2, y2 = map(int, rec["bike_box"])
            cv2.rectangle(frame, (x1, y1), (x2, y2), CYAN, 2)
            cv2.putText(frame, f"bike {rec.get('bike_conf', 0):.2f}",
                        (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, CYAN, 1, cv2.LINE_AA)
        kps = rec.get("keypoints", {})
        for a, b in SKELETON_EDGES:
            if a in kps and b in kps:
                pa, pb = kps[a], kps[b]
                cv2.line(frame, (int(pa[0]), int(pa[1])),
                         (int(pb[0]), int(pb[1])), GREEN, 2, cv2.LINE_AA)
        for p in kps.values():
            cv2.circle(frame, (int(p[0]), int(p[1])), 3, WHITE, -1, cv2.LINE_AA)

        y = 24
        for label, key in (("hip", "hip_angle"), ("knee", "knee_angle"),
                           ("elbow", "elbow_angle")):
            v = rec.get(key)
            if v is not None:
                cv2.putText(frame, f"{label}: {v:5.1f} deg", (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, GREEN, 1, cv2.LINE_AA)
                y += 22

    # suspension-activity meter, bottom-left
    bar_w, bar_h = 180, 14
    x0, y0 = 10, h - 24
    cv2.rectangle(frame, (x0, y0), (x0 + bar_w, y0 + bar_h), WHITE, 1)
    cv2.rectangle(frame, (x0, y0),
                  (x0 + int(bar_w * np.clip(score, 0, 1)), y0 + bar_h),
                  ORANGE, -1)
    cv2.putText(frame, f"suspension activity {score:.2f}", (x0, y0 - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, ORANGE, 1, cv2.LINE_AA)
    return frame


def export_highlights(video_path: str | Path, track_json: str | Path,
                      score_json: str | Path, windows: list[tuple[float, float, float]],
                      out_dir: str | Path) -> list[dict]:
    """Write one annotated MP4 + peak-frame PNG per window; return a manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    track_data = json.loads(Path(track_json).read_text())
    lookup = _frame_lookup(track_data)
    sdata = json.loads(Path(score_json).read_text())
    times = np.array(sdata["times"])
    scores = np.array(sdata["scores"])

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    manifest = []
    for rank, (start, end, mean_score) in enumerate(windows, 1):
        clip_path = out_dir / f"highlight_{rank:02d}_{start:07.2f}s.mp4"
        still_path = out_dir / f"highlight_{rank:02d}_{start:07.2f}s_peak.png"

        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        writer = None
        peak = (-1.0, None)  # (score, annotated frame)
        while True:
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            ok, frame = cap.read()
            if not ok or t > end:
                break
            idx = int(round(t * fps))
            rec = lookup.get(idx)
            s = _score_at(times, scores, t)
            annotated = annotate(frame, rec, s)
            if writer is None:
                h, w = annotated.shape[:2]
                writer = cv2.VideoWriter(str(clip_path),
                                         cv2.VideoWriter_fourcc(*"mp4v"),
                                         fps, (w, h))
            writer.write(annotated)
            if s > peak[0]:
                peak = (s, annotated.copy())
        if writer:
            writer.release()
        if peak[1] is not None:
            cv2.imwrite(str(still_path), peak[1])

        manifest.append({
            "rank": rank, "start_s": round(start, 2), "end_s": round(end, 2),
            "mean_score": round(mean_score, 3), "peak_score": round(peak[0], 3),
            "clip": clip_path.name, "still": still_path.name,
        })
    cap.release()

    (out_dir / "highlights.json").write_text(json.dumps(manifest, indent=1))
    return manifest
