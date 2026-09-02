"""Cornering analysis: find turns, measure how the rider rotates through
them, and expose the per-turn features an advanced-vs-other comparison
needs.

Turn detection is from the tracking record alone: sustained lean (the
attitude roll proxy) or sustained lateral drift of the bike's image
position, in either direction, held for >= MIN_TURN_S seconds.

Per-turn metrics (all 2D proxies from one camera -- see attitude.py):
  peak_lean_deg      -- max |lean| through the turn
  lean_smoothness    -- 1 / (1 + mean |d lean / dt|): high = one clean arc,
                        low = sawing at the bars / correcting mid-turn
  gaze_lead_pct      -- share of the turn where the sightline is level or
                        raised (looking through the exit) rather than
                        dropped at the front wheel
  counter_rotation   -- mean |shoulder-line angle - hip-line angle|: how
                        much the upper body is turned relative to the hips
  entry_speed_proxy  -- bike apparent-size growth rate in the second before
                        the turn (approach speed, chase/static cams only)
  exit_speed_ratio   -- apparent-size growth after / before the apex:
                        > 1 = carried or gained speed, < 1 = scrubbed
  elbow_drop, knee_bend -- mean elbow / knee angle through the turn: the
                        classic "outside elbow up, inside knee in" cues
                        show up as asymmetry between sides when visible

These feed form_grade.factor_report(): with enough runs labeled by level
in riders.yaml, the report ranks which of these separate advanced riders
from the rest. Until then the metrics are reported per turn without a
verdict.
"""

from __future__ import annotations

import math

import numpy as np

MIN_TURN_S = 0.6
LEAN_THRESH_DEG = 8.0


def _interp(x):
    x = np.asarray(x, dtype=float)
    nans = np.isnan(x)
    if nans.all():
        return np.zeros_like(x)
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def _line_angle(kps, l, r):
    if l in kps and r in kps:
        (x1, y1), (x2, y2) = kps[l][:2], kps[r][:2]
        return math.degrees(math.atan2(y2 - y1, x2 - x1))
    return None


def find_turns(frames: list[dict], fps: float) -> list[dict]:
    """Segments where |lean| exceeds LEAN_THRESH_DEG for >= MIN_TURN_S."""
    lean = _interp([f.get("attitude", {}).get("lean_deg") if f.get("attitude", {}).get("lean_deg") is not None else np.nan
                    for f in frames])
    # smooth ~0.3 s
    win = max(3, int(0.3 * fps) | 1)
    lean_s = np.convolve(np.pad(lean, win // 2, mode="edge"), np.ones(win) / win, mode="valid")[: len(lean)]
    active = np.abs(lean_s) > LEAN_THRESH_DEG
    turns, start = [], None
    min_len = int(MIN_TURN_S * fps)
    for i, a in enumerate(list(active) + [False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            if i - start >= min_len:
                seg = lean_s[start:i]
                turns.append({"start_idx": start, "end_idx": i - 1,
                              "start_s": round(frames[start]["time_s"], 2),
                              "end_s": round(frames[i - 1]["time_s"], 2),
                              "direction": "left" if seg.mean() < 0 else "right",
                              "apex_idx": start + int(np.argmax(np.abs(seg)))})
            start = None
    return turns


def _size_series(frames):
    return _interp([(f["bike_box"][2] - f["bike_box"][0]) if f.get("bike_box") else np.nan
                    for f in frames])


def turn_metrics(frames: list[dict], fps: float, turn: dict) -> dict:
    s, e, apex = turn["start_idx"], turn["end_idx"], turn["apex_idx"]
    seg = frames[s:e + 1]
    lean = _interp([f.get("attitude", {}).get("lean_deg") if f.get("attitude", {}).get("lean_deg") is not None else np.nan for f in seg])
    gaze = np.array([f.get("gaze_angle") for f in seg], dtype=float)
    elbow = np.array([f.get("elbow_angle") for f in seg], dtype=float)
    knee = np.array([f.get("knee_angle") for f in seg], dtype=float)

    rot = []
    for f in seg:
        k = f.get("keypoints", {})
        a, b = _line_angle(k, "l_shoulder", "r_shoulder"), _line_angle(k, "l_hip", "r_hip")
        if a is not None and b is not None:
            d = abs(a - b) % 180
            rot.append(min(d, 180 - d))

    size = _size_series(frames)
    pre = slice(max(0, s - int(fps)), s + 1)
    post = slice(apex, min(len(frames), apex + int(fps) + 1))
    def growth(sl):
        v = size[sl]
        if len(v) < 3 or v[0] <= 0:
            return None
        return float((v[-1] - v[0]) / v[0])
    g_pre, g_post = growth(pre), growth(post)

    lean_rate = np.abs(np.gradient(lean)) * fps if len(lean) > 2 else np.array([0.0])
    return {
        **{k: turn[k] for k in ("start_s", "end_s", "direction")},
        "duration_s": round(turn["end_s"] - turn["start_s"], 2),
        "peak_lean_deg": round(float(np.max(np.abs(lean))), 1) if len(lean) else None,
        "lean_smoothness": round(float(1.0 / (1.0 + lean_rate.mean())), 3),
        "gaze_lead_pct": round(float(100 * np.nanmean(gaze <= 25)), 1) if np.isfinite(gaze).any() else None,
        "counter_rotation_deg": round(float(np.mean(rot)), 1) if rot else None,
        "entry_speed_proxy": round(g_pre, 3) if g_pre is not None else None,
        "exit_speed_ratio": (round((1 + g_post) / (1 + g_pre), 3)
                             if g_pre is not None and g_post is not None and (1 + g_pre) > 0 else None),
        "mean_elbow_deg": round(float(np.nanmean(elbow)), 1) if np.isfinite(elbow).any() else None,
        "mean_knee_deg": round(float(np.nanmean(knee)), 1) if np.isfinite(knee).any() else None,
    }


def analyze_cornering(frames: list[dict], fps: float) -> dict:
    turns = find_turns(frames, fps)
    metrics = [turn_metrics(frames, fps, t) for t in turns]
    summary = {}
    if metrics:
        for key in ("peak_lean_deg", "lean_smoothness", "gaze_lead_pct",
                    "counter_rotation_deg", "exit_speed_ratio"):
            vals = [m[key] for m in metrics if m.get(key) is not None]
            summary[key] = round(float(np.mean(vals)), 3) if vals else None
    return {"turns": metrics, "n_turns": len(metrics), "summary": summary,
            "note": "2D proxies from a single camera; lean and speed are relative cues, not calibrated values"}
