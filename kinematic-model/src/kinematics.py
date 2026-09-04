"""Rotation rates and ground speed from the tracking record.

Rates are time derivatives of the attitude proxies already on each frame:

  pitch_rate  -- d/dt of pitch: the bike's axle line in side views (from
                 wheels.py), else the mask principal axis (attitude.py)
  roll_rate   -- d/dt of lean: bike lean in rear/chase views, else the
                 rider's torso tilt
  yaw_rate    -- d/dt of the heading proxy: the axle line's projected
                 length relative to the wheel diameter gives how far the
                 bike is turned from broadside (0 deg broadside, 90 deg
                 end-on); as the bike rotates through a turn that angle
                 sweeps, and its rate is the yaw rate *magnitude*

All in degrees per second, from angles smoothed over ~0.2 s, with no
interpolation across gaps longer than 0.4 s (a rate needs neighbours that
were actually measured). Spikes above MAX_PLAUSIBLE_RATE are fit noise
(a bike does not rotate 720 deg/s) and are dropped before the maxima are
taken. Signed where the proxy has a sign (pitch, roll), unsigned for yaw.

Speed is estimated from the ground: in a chase view the terrain streams
past at the bike's speed. The shift of a wide band at the bike's image
depth (its wheel line) between consecutive frames, found by phase
correlation (which survives motion blur far better than dense optical
flow, whose estimate collapses toward zero on a smeared surface), gives
px/frame; the wheel-diameter scale from wheels.py turns that into mm, and
fps into m/s. It is a chase-cam estimate, not GPS: the camera's own motion
relative to the bike adds error, expect +-30%, and it is blank where the
ground is untextured or the bike scale is unknown.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

MAX_PLAUSIBLE_RATE = 450.0     # deg/s: a DH bike does not rotate faster than this about any axis


def _unwrap180(x):
    """Axis angles live in (-90, 90]: a wheel-line or mask axis passing
    through vertical flips sign, which would read as a 180 deg/frame jump.
    Unwrap with period 180 so the series is continuous before differencing."""
    x = np.array(x, float)
    ok = ~np.isnan(x)
    if ok.sum() < 2:
        return x
    out = x.copy()
    vals = np.unwrap(np.radians(x[ok]) * 2.0) / 2.0   # period pi in radians == 180 deg
    out[ok] = np.degrees(vals)
    return out
MAX_GAP_S = 0.4
SPEED_MIN_KMH, SPEED_MAX_KMH = 3.0, 95.0


def _series(frames, getter):
    return np.array([getter(f) if getter(f) is not None else np.nan for f in frames], float)


def _smooth_gapped(x, fps, win_s=0.2, max_gap_s=MAX_GAP_S):
    """Smooth with a short window; fill only gaps shorter than max_gap."""
    x = np.array(x, float)
    n = len(x)
    ok = ~np.isnan(x)
    if ok.sum() < 3:
        return np.full(n, np.nan)
    idx = np.arange(n)
    filled = x.copy()
    filled[~ok] = np.interp(idx[~ok], idx[ok], x[ok])
    # re-blank long gaps
    max_gap = int(max_gap_s * fps)
    start = None
    for i in range(n + 1):
        if i < n and not ok[i]:
            if start is None:
                start = i
        elif start is not None:
            if i - start > max_gap:
                filled[start:i] = np.nan
            start = None
    win = max(3, int(win_s * fps) | 1)
    k = np.ones(win) / win
    out = np.full(n, np.nan)
    valid = ~np.isnan(filled)
    padded = np.pad(np.where(valid, filled, 0.0), win // 2, mode="edge")
    wpad = np.pad(valid.astype(float), win // 2, mode="edge")
    num = np.convolve(padded, k, mode="valid")[:n]
    den = np.convolve(wpad, k, mode="valid")[:n]
    good = den > 0.6
    out[good] = num[good] / den[good]
    return out


def _rate(x, fps):
    r = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    if ok.sum() < 3:
        return r
    g = np.gradient(np.where(ok, x, 0.0)) * fps
    # only where both neighbours exist
    both = ok.copy()
    both[1:] &= ok[:-1]; both[:-1] &= ok[1:]
    r[both] = g[both]
    r[np.abs(r) > MAX_PLAUSIBLE_RATE] = np.nan
    return r


def rotation_rates(frames: list[dict], fps: float) -> dict:
    """Attach pitch/roll/yaw rate to each frame (mutates) and return maxima."""
    def att(k):
        return lambda f: (f.get("attitude") or {}).get(k)
    def geom(k):
        return lambda f: (f.get("bike_geom") or {}).get(k)

    view = [(f.get("attitude") or {}).get("view") for f in frames]
    axle = _series(frames, geom("axle_line_deg"))
    pitch_mask = _series(frames, att("pitch_deg"))
    # pitch: axle line where both wheels are seen side-on, else the mask axis
    pitch = _unwrap180(np.where(~np.isnan(axle) & np.array([v == "side" for v in view]), axle, pitch_mask))
    lean = _unwrap180(_series(frames, att("lean_deg")))
    torso = _series(frames, att("torso_tilt_deg"))
    roll = np.where(~np.isnan(lean), lean, torso)
    yawp = _series(frames, geom("yaw_proxy"))         # 0 end-on .. 1 broadside
    yaw = np.degrees(np.arccos(np.clip(yawp, 0, 1)))  # 0 broadside .. 90 end-on
    elong = _series(frames, att("yaw_proxy"))
    yaw_fallback = np.clip(90.0 * (1.0 - elong / 0.75), 0, 90)
    yaw = np.where(~np.isnan(yaw), yaw, yaw_fallback)

    out = {}
    series = {}
    for name, x in (("pitch", pitch), ("roll", roll), ("yaw", yaw)):
        s = _smooth_gapped(x, fps, win_s=0.3)
        r = _rate(s, fps)
        series[name] = (s, r)
        finite = np.isfinite(r)
        if finite.sum() >= 3:
            i = int(np.nanargmax(np.abs(np.where(finite, r, 0.0))))
            out[name] = {"max_abs_deg_s": round(float(abs(r[i])), 1), "at_s": round(frames[i]["time_s"], 2),
                         "signed_at_max": round(float(r[i]), 1),
                         "p95_abs_deg_s": round(float(np.nanpercentile(np.abs(r[finite]), 95)), 1),
                         "rms_deg_s": round(float(np.sqrt(np.nanmean(r[finite] ** 2))), 1),
                         "coverage": round(float(finite.mean()), 2)}
        else:
            out[name] = None
    for i, f in enumerate(frames):
        f["rates"] = {f"{k}_rate_deg_s": (None if np.isnan(series[k][1][i]) else round(float(series[k][1][i]), 1)) for k in series}
        f["rates"].update({f"{k}_deg": (None if np.isnan(series[k][0][i]) else round(float(series[k][0][i]), 1)) for k in series})
    out["note"] = ("rates are derivatives of monocular attitude proxies: pitch from the axle line / mask axis, "
                   "roll from bike lean or torso tilt, yaw as the unsigned sweep of the heading proxy; "
                   f"spikes above {MAX_PLAUSIBLE_RATE:.0f} deg/s dropped as fit noise; not IMU data")
    return out


def _band_shift(a, b):
    """Dominant image shift between two same-size grey bands, px, by phase
    correlation with a Hanning window. Returns (dx, dy, response)."""
    fa, fb = a.astype(np.float32), b.astype(np.float32)
    win = cv2.createHanningWindow((fa.shape[1], fa.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(fa, fb, win)
    return dx, dy, resp


def speed_series(video_path, frames: list[dict], rot_code, fps: float, downscale: int = 2) -> dict:
    """Ground-shift speed estimate per frame (mutates frames; returns summary)."""
    cap = cv2.VideoCapture(str(video_path))
    by_idx = {f["frame"]: f for f in frames}
    prev = None
    i = 0
    speeds = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if rot_code is not None:
            frame = cv2.rotate(frame, rot_code)
        small = cv2.cvtColor(cv2.resize(frame, None, fx=1.0 / downscale, fy=1.0 / downscale,
                                        interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        rec = by_idx.get(i)
        v_kmh = None
        if prev is not None and rec is not None and rec.get("bike_box"):
            mmpp = (rec.get("bike_geom") or {}).get("mm_per_px")
            x1, y1, x2, y2 = [v / downscale for v in rec["bike_box"]]
            bh = max(y2 - y1, 4.0)
            if mmpp is None:
                # fallback scale: a DH bike + rider box is ~1.35 m tall
                mmpp = 1350.0 / max(rec["bike_height"], 1.0)
            h, w = small.shape
            band_y0, band_y1 = int(max(0, y2 - 0.3 * bh)), int(min(h, y2 + 1.2 * bh))
            # the ground on either side of the bike, at its depth
            bx0, bx1 = int(max(0, x1 - 0.3 * bh)), int(min(w, x2 + 0.3 * bh))
            shifts = []
            for sx0, sx1 in ((0, bx0), (bx1, w)):
                if sx1 - sx0 >= 96 and band_y1 - band_y0 >= 24:
                    a, b = prev[band_y0:band_y1, sx0:sx1], small[band_y0:band_y1, sx0:sx1]
                    if float(cv2.Laplacian(b, cv2.CV_64F).var()) > 8.0:
                        dx, dy, resp = _band_shift(a, b)
                        if resp > 0.05:
                            shifts.append((math.hypot(dx, dy), resp))
            if shifts:
                px_frame = max(shifts, key=lambda s: s[1])[0] * downscale
                v_kmh = px_frame * mmpp * fps / 1000.0 * 3.6
                if not (SPEED_MIN_KMH <= v_kmh <= SPEED_MAX_KMH):
                    v_kmh = None
        if rec is not None:
            rec["speed_kmh_est"] = round(v_kmh, 1) if v_kmh is not None else None
            speeds.append(v_kmh if v_kmh is not None else np.nan)
        prev = small
        i += 1
    cap.release()
    s = np.array(speeds, float)
    # smooth over ~0.5 s for the readout
    if np.isfinite(s).any():
        sm = _smooth_gapped(s, fps, win_s=0.5, max_gap_s=0.6)
        for f, v in zip(frames, sm):
            f["speed_kmh_smooth"] = None if np.isnan(v) else round(float(v), 1)
        fin = s[np.isfinite(s)]
        return {"median_kmh": round(float(np.median(fin)), 1), "p95_kmh": round(float(np.percentile(fin, 95)), 1),
                "max_kmh": round(float(np.nanmax(sm)), 1), "at_s": round(frames[int(np.nanargmax(sm))]["time_s"], 2),
                "coverage": round(float(np.isfinite(s).mean()), 2),
                "note": "chase-cam ground-shift estimate (phase correlation) scaled by wheel diameter (or bike height when wheels are missing); +-30%, not GPS"}
    return {"median_kmh": None, "coverage": 0.0, "note": "no textured ground at the bike's depth to estimate speed from"}
