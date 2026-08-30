"""Suspension-activity scoring.

Detects windows where the suspension is cycling in rough terrain from the
tracking output. The physical signal: when suspension compresses and
rebounds, the bike oscillates vertically at higher frequency than the
rider's body (the rider's legs and arms absorb the motion), and the bike
box height "breathes" as the wheels move relative to the frame. We score:

  1. High-frequency vertical oscillation of the bike center
     (residual after removing the slow camera/trajectory component).
  2. Rate of change of knee + elbow angles (rider actively absorbing hits).
  3. Bike-height oscillation (axle-to-frame travel proxy).

Scores are combined, smoothed, and normalized to [0, 1] per video.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _interp_nan(x: np.ndarray) -> np.ndarray:
    """Linearly fill NaNs so filtering works across dropped detections."""
    x = x.astype(float).copy()
    nans = np.isnan(x)
    if nans.all():
        return np.zeros_like(x)
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def _highpass(x: np.ndarray, win: int) -> np.ndarray:
    """Signal minus its moving average: keeps the fast oscillation."""
    win = max(3, win | 1)  # odd
    kernel = np.ones(win) / win
    slow = np.convolve(np.pad(x, win // 2, mode="edge"), kernel, mode="valid")
    return x - slow[: len(x)]


def _rolling_rms(x: np.ndarray, win: int) -> np.ndarray:
    win = max(3, win | 1)
    kernel = np.ones(win) / win
    sq = np.convolve(np.pad(x**2, win // 2, mode="edge"), kernel, mode="valid")
    return np.sqrt(np.clip(sq[: len(x)], 0, None))


def suspension_score(track_json: str | Path, out_json: str | Path | None = None):
    """Return (times, scores) arrays; optionally persist them to JSON."""
    data = json.loads(Path(track_json).read_text())
    frames = data["frames"]
    fps = data.get("fps", 30.0) / max(1, data.get("stride", 1))

    def series(getter):
        return _interp_nan(np.array(
            [getter(f) if getter(f) is not None else np.nan for f in frames]))

    center_y = series(lambda f: f.get("bike_center_y"))
    bike_h = series(lambda f: f.get("bike_height"))
    knee = series(lambda f: f.get("knee_angle"))
    elbow = series(lambda f: f.get("elbow_angle"))
    times = np.array([f["time_s"] for f in frames])

    half_sec = max(3, int(fps / 2))

    # 1. fast vertical chatter of the bike, normalized by bike size
    scale = np.maximum(np.nanmedian(bike_h[bike_h > 0]) if (bike_h > 0).any() else 1.0, 1.0)
    chatter = _rolling_rms(_highpass(center_y, half_sec), half_sec) / scale

    # 2. rider absorption: how fast knee/elbow angles are changing (deg/s)
    absorb = _rolling_rms(np.gradient(knee) * fps, half_sec) / 90.0 \
        + _rolling_rms(np.gradient(elbow) * fps, half_sec) / 90.0

    # 3. bike-height breathing (travel proxy)
    breathe = _rolling_rms(_highpass(bike_h, half_sec), half_sec) / scale

    raw = 0.5 * chatter + 0.3 * absorb + 0.2 * breathe

    # confidence gate: no bike detection -> no score
    has_bike = np.array([f.get("bike_box") is not None for f in frames], dtype=float)
    kernel = np.ones(half_sec) / half_sec
    gate = np.convolve(np.pad(has_bike, half_sec // 2, mode="edge"), kernel,
                       mode="valid")[: len(raw)]
    raw = raw * gate

    lo, hi = np.percentile(raw, 5), np.percentile(raw, 99)
    scores = np.clip((raw - lo) / (hi - lo + 1e-9), 0, 1)

    if out_json:
        out = Path(out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "video": data.get("video"),
            "times": times.tolist(),
            "scores": scores.tolist(),
        }, indent=1))
    return times, scores


def pick_windows(times: np.ndarray, scores: np.ndarray,
                 n: int = 6, clip_len_s: float = 5.0,
                 min_gap_s: float = 3.0,
                 min_score: float = 0.25) -> list[tuple[float, float, float]]:
    """Pick up to n non-overlapping windows with the highest mean score.

    Windows scoring below min_score are dropped — better to export fewer
    shots than shots where the suspension isn't actually working.
    Returns [(start_s, end_s, mean_score)] sorted by score descending.
    """
    if len(times) < 2:
        return []
    dt = float(np.median(np.diff(times)))
    win = max(1, int(clip_len_s / dt))
    kernel = np.ones(win) / win
    means = np.convolve(scores, kernel, mode="valid")

    picked, used = [], np.zeros(len(means), dtype=bool)
    gap = int(min_gap_s / dt)
    order = np.argsort(means)[::-1]
    for i in order:
        if means[i] < min_score:
            break
        if used[max(0, i - gap): i + win + gap].any():
            continue
        start = float(times[i])
        end = float(times[min(i + win, len(times) - 1)])
        picked.append((start, end, float(means[i])))
        used[max(0, i - gap): min(len(means), i + win + gap)] = True
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda w: -w[2])
