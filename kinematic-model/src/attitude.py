"""Bike attitude (pitch / roll / yaw) from monocular video.

Honest framing: a single uncalibrated camera cannot recover true 3D
attitude. What it can recover, per frame, from the bike's segmentation
mask and the rider's keypoints:

  pitch_deg   -- inclination of the bike's major axis vs. the image
                 horizontal (side-on views: nose-up positive). Robust
                 when the bike is seen broadly from the side.
  lean_deg    -- tilt of the bike's major axis vs. the image vertical in
                 compact (front/rear/chase) views, plus the rider's torso
                 tilt vs. vertical. This is the roll proxy: in a rear or
                 chase view, a cornering bike leans visibly.
  yaw_proxy   -- 0..1 from the mask's elongation: ~1 = broadside to the
                 camera, ~0 = pointed at/away from it. It is a *relative*
                 heading cue, useful for detecting a turn as the bike
                 rotates through it, not an absolute heading.
  view        -- "side" | "compact" | "unknown", from the same elongation,
                 so downstream code knows which of pitch/lean to trust.

Everything here is labeled as a proxy in the output so a consumer never
mistakes it for IMU-grade attitude. Real yaw/pitch/roll needs a second
camera or on-bike IMU data; the metadata form on the upload path asks
for those when riders have them.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def mask_axis(mask: np.ndarray | None):
    """Principal axis of a binary mask via PCA of its pixel coordinates.

    Returns (angle_from_horizontal_deg, elongation, centroid) or None.
    angle is in image coordinates, positive = counter-clockwise on screen
    (y up), range (-90, 90]. elongation = 1 - minor/major in [0, 1).
    """
    if mask is None:
        return None
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return None
    pts = np.stack([xs, -ys], axis=1).astype(np.float64)  # y up
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T)
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, np.argmax(evals)]
    angle = math.degrees(math.atan2(major[1], major[0]))
    if angle > 90:
        angle -= 180
    elif angle <= -90:
        angle += 180
    lo, hi = float(np.min(evals)), float(np.max(evals))
    elong = 1.0 - math.sqrt(max(lo, 1e-9) / max(hi, 1e-9))
    return angle, elong, (float(mean[0]), float(-mean[1]))


def torso_tilt(kps: dict) -> float | None:
    """Signed tilt of the hip->shoulder line vs. image vertical, degrees.
    Positive = shoulders displaced to screen-right of hips."""
    def avg(l, r):
        pts = [kps[k] for k in (l, r) if k in kps]
        return np.mean([p[:2] for p in pts], axis=0) if pts else None
    hip, sh = avg("l_hip", "r_hip"), avg("l_shoulder", "r_shoulder")
    if hip is None or sh is None:
        return None
    dx, dy = sh[0] - hip[0], hip[1] - sh[1]  # dy up
    if abs(dx) + abs(dy) < 1e-6:
        return None
    return math.degrees(math.atan2(dx, max(dy, 1e-6)))


def attitude_from_frame(bike_mask: np.ndarray | None, kps: dict) -> dict:
    """Per-frame attitude proxies. All keys present; None where unknown."""
    out = {"pitch_deg": None, "lean_deg": None, "torso_tilt_deg": None,
           "yaw_proxy": None, "view": "unknown", "proxy": True}
    ax = mask_axis(bike_mask)
    if ax:
        angle, elong, _ = ax
        out["yaw_proxy"] = round(elong, 3)
        if elong >= 0.55:
            out["view"] = "side"
            out["pitch_deg"] = round(angle, 1)
        elif elong <= 0.35:
            out["view"] = "compact"
            # major axis near vertical in a rear view; lean = deviation from it
            lean = angle - 90 if angle > 0 else angle + 90
            out["lean_deg"] = round(lean, 1)
    tt = torso_tilt(kps)
    if tt is not None:
        out["torso_tilt_deg"] = round(tt, 1)
        if out["lean_deg"] is None and out["view"] != "side":
            out["lean_deg"] = round(tt, 1)  # rider lean stands in for bike lean
    return out


def attitude_series(track_frames: list[dict], masks_by_idx: dict[int, np.ndarray] | None):
    """Attach attitude proxies to each tracked frame (mutates + returns)."""
    for f in track_frames:
        m = masks_by_idx.get(f["frame"]) if masks_by_idx else None
        f["attitude"] = attitude_from_frame(m, f.get("keypoints", {}))
    return track_frames
