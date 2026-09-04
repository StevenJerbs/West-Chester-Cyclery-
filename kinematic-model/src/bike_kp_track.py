"""Temporal refinement of the DH bike keypoints (front_axle, rear_axle,
fork_crown, bottom_bracket) across a run.

The per-frame detector places each point with a median error of 14-20 px
and no memory between frames, so the raw series jitters by about that much
frame to frame -- more than the fork moves between two frames at 25 fps.
Within a shot the points move smoothly, so each frame's points are also
predicted from the previous frame with pyramidal Lucas-Kanade optical flow
(forward-backward checked) and fused with the detection:

  detection near the LK prediction  -> weighted average, source "fused"
  detection far from it, confident  -> the detection wins (fast motion, or
                                       LK drifted), source "det"
  no usable detection               -> the LK prediction carries for up to
                                       `max_carry` frames with decaying
                                       confidence, source "lk"
  shot change / long gap            -> reset, next detection starts fresh

Mutates each frame: `bike_kps` becomes the refined points, the detector's
own output is kept in `bike_kps_raw`, and `bike_kps_src` says which rule
produced each point. mtbkin measured the same idea on a hardtail (whose
BB-to-rear-axle distance must be constant): detector 14.4 px spread ->
LK 3.3 px -> CoTracker 1.1 px. LK is used here because it is CPU-cheap and
needs no extra model; CoTracker is the upgrade if sub-2 px is ever needed.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from track import BIKE_KP, _ROTATIONS

LK = dict(winSize=(21, 21), maxLevel=3,
          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def _box_jump(a, b):
    """Bike box moved more than its own size between frames -> treat as a cut."""
    if a is None or b is None:
        return False
    sa = max(a[2] - a[0], a[3] - a[1], 1.0)
    d = math.hypot((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2, (a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)
    return d > 1.0 * sa


def refine_bike_kps(video_path: str | Path, track: dict, rotate_deg: int = 0,
                    max_carry: int = 15, fb_tol_px: float = 2.0, min_conf: float = 0.5,
                    alpha: float = 0.25, snap_after: int = 2) -> dict:
    """Refine `bike_kps` in place for every frame of `track`. Returns stats."""
    frames = track["frames"]
    by_idx = {f["frame"]: f for f in frames}
    code = _ROTATIONS.get(rotate_deg % 360)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    prev_gray = None
    prev_pts: dict[str, np.ndarray] = {}      # name -> (x, y) refined, last frame
    prev_conf: dict[str, float] = {}
    carried: dict[str, int] = {}
    prev_box = None
    disagree: dict[str, int] = {}             # consecutive frames the detection sat far from the LK prior
    stats = {"det": 0, "fused": 0, "lk": 0, "reset": 0, "frames_with_kps_before": 0, "frames_with_kps_after": 0}
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if code is not None:
            frame = cv2.rotate(frame, code)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rec = by_idx.get(i)
        if rec is None:
            prev_gray, prev_pts, prev_conf, carried, prev_box = gray, {}, {}, {}, None
            i += 1
            continue
        raw = dict(rec.get("bike_kps") or {})
        rec["bike_kps_raw"] = raw
        if any(v[2] >= min_conf for v in raw.values()):
            stats["frames_with_kps_before"] += 1
        box = rec.get("bike_box")

        # shot change: drop the memory
        if _box_jump(prev_box, box) or (box is None and prev_box is None and prev_pts):
            if prev_pts:
                stats["reset"] += 1
            prev_pts, prev_conf, carried = {}, {}, {}

        # LK prediction for every remembered point
        pred: dict[str, np.ndarray] = {}
        if prev_gray is not None and prev_pts:
            names = list(prev_pts)
            p0 = np.array([prev_pts[n] for n in names], np.float32).reshape(-1, 1, 2)
            p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, p0, None, **LK)
            if p1 is not None:
                p0b, stb, _ = cv2.calcOpticalFlowPyrLK(gray, prev_gray, p1, None, **LK)
                fb = np.linalg.norm(p0.reshape(-1, 2) - p0b.reshape(-1, 2), axis=1)
                for k, n in enumerate(names):
                    if st[k] and stb[k] and fb[k] < fb_tol_px:
                        pred[n] = p1[k, 0].copy()

        out: dict[str, list] = {}
        src: dict[str, str] = {}
        for n in BIKE_KP:
            det = raw.get(n)
            det_ok = det is not None and det[2] >= min_conf
            lk = pred.get(n)
            if det_ok and lk is not None:
                gate = 0.35 * max(box[2] - box[0], box[3] - box[1]) if box else 40.0
                d = math.hypot(det[0] - lk[0], det[1] - lk[1])
                if d < gate:
                    # the flow prediction is the prior; the detection only nudges it, harder
                    # when confident. This is what removes the detector's frame-to-frame jitter.
                    a = alpha * min(1.0, det[2] / 0.75)
                    x, y = lk[0] + a * (det[0] - lk[0]), lk[1] + a * (det[1] - lk[1])
                    out[n], src[n] = [float(x), float(y), float(det[2])], "fused"
                    disagree[n] = 0
                else:
                    # LK may have drifted, or the bike moved faster than the flow window: hold the
                    # prior for a frame or two, then snap to the detector if it keeps disagreeing
                    disagree[n] = disagree.get(n, 0) + 1
                    if disagree[n] > snap_after:
                        out[n], src[n] = [float(det[0]), float(det[1]), float(det[2])], "det"
                        disagree[n] = 0
                    else:
                        out[n], src[n] = [float(lk[0]), float(lk[1]), float(det[2])], "fused"
                carried[n] = 0
            elif det_ok:
                out[n], src[n] = [float(det[0]), float(det[1]), float(det[2])], "det"
                carried[n] = 0
            elif lk is not None and carried.get(n, 0) < max_carry:
                carried[n] = carried.get(n, 0) + 1
                conf = prev_conf.get(n, min_conf) * 0.9
                if conf >= min_conf:
                    out[n], src[n] = [float(lk[0]), float(lk[1]), float(conf)], "lk"
        for s in src.values():
            stats[s] += 1
        if out:
            stats["frames_with_kps_after"] += 1
        rec["bike_kps"] = out
        rec["bike_kps_src"] = src
        prev_pts = {n: np.array(v[:2], np.float32) for n, v in out.items()}
        prev_conf = {n: v[2] for n, v in out.items()}
        prev_gray, prev_box = gray, box
        i += 1
    cap.release()
    return stats
