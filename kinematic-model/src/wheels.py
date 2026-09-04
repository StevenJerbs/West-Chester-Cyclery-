"""Wheel, axle and suspension geometry from monocular video.

What a single camera can measure about the bike below the rider, per frame,
given the bike's segmentation mask (outline.py) and the rider keypoints:

  wheel ellipses      -- the two thickest compact blobs of the bike
                         silhouette are the tyres. Each is fitted with an
                         ellipse: centre = axle position, major axis = the
                         wheel's true outside diameter under projection
                         (which is what gives the millimetre scale), and
                         minor/major = the cosine of how far the wheel plane
                         is turned away from the camera.
  camber / roll       -- the ellipse's in-plane tilt of its major axis from
                         vertical (rear or chase views) is the wheel's roll
                         angle relative to the image vertical. The
                         minor/major ratio is the out-of-plane tilt. Both are
                         reported; which one is "roll" depends on the view,
                         and the view is reported alongside.
  pitch / roll / yaw  -- the axle-to-axle line: its angle from horizontal is
                         pitch in side views and roll in rear views; its
                         length relative to the wheel diameter is a yaw proxy
                         (broadside ~1.7 for a DH bike, end-on ~0).
  fork / rear travel  -- sprung-vs-unsprung distances. The hands sit on the
                         bars (sprung) and the feet on the pedals (sprung,
                         at the BB); the axles are unsprung. Front axle ->
                         wrist distance shortens as the fork compresses,
                         rear axle -> ankle distance as the shock does. Each
                         is reported as compression from the run's own
                         extended baseline, in mm via the wheel scale, and
                         as a share of the bike's travel when specs exist.
  ground contact      -- heuristic: (a) textured ground directly under the
                         lowest point of the tyre, (b) the tyre-bottom's
                         image motion agreeing with the ground's just below
                         it. Rolling contact satisfies both; an airborne
                         wheel fails (b) by parallax and usually (a).
  deflection          -- fast axle motion relative to the frame (mask
                         centroid): vertical = tyre/suspension compliance
                         over hits, lateral = the wheel stepping sideways.

Sidewall deformation is *not* resolvable at these pixel scales (a 2.5"
tyre at ~120 px diameter has a ~5 px sidewall) and is not reported.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- specs

def load_bike_specs(bike_id: str | None = None) -> dict:
    import yaml
    spec = yaml.safe_load((ROOT / "data" / "bike_specs.yaml").read_text())
    base = dict(spec.get("default", {}))
    if bike_id and bike_id in spec.get("bikes", {}):
        base.update(spec["bikes"][bike_id])
    return base


# ---------------------------------------------------------- wheel finding

def _wheel_blobs(bike_mask: np.ndarray, box_h: float):
    """Tyres are the two thickest compact regions of the bike silhouette.

    A single morphological opening cannot separate a wheel from the rear
    triangle or a leg the segmenter glued to it, so instead: take the two
    strongest peaks of the distance transform (the centres of the thickest
    regions, at least ~0.7 wheel diameters apart), cut the silhouette to a
    disc of 1.25 x the expected wheel radius around each peak, and fit an
    ellipse to what is left. The disc clips the attached frame/leg; the
    ellipse still recovers the wheel's true major axis from the tyre arc.
    Expected radius comes from the peak's own distance value (the inscribed
    circle of a wheel blob is the wheel's minor semi-axis) and the bike box
    (a wheel is 0.2..0.45 box heights in radius across any view).
    """
    if bike_mask is None or bike_mask.max() == 0:
        return []
    dt = cv2.distanceTransform((bike_mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    r_lo, r_hi = 0.12 * box_h, 0.46 * box_h
    blobs, taken = [], np.zeros_like(bike_mask, dtype=bool)
    for _ in range(3):
        dt_m = np.where(taken, 0, dt)
        idx = np.unravel_index(int(np.argmax(dt_m)), dt.shape)
        py, px = int(idx[0]), int(idx[1])
        r_in = float(dt[py, px])
        if r_in < 0.5 * r_lo:
            break
        r_exp = float(np.clip(r_in * 1.6, r_lo, r_hi))     # end-on wheel: r_in is minor semi-axis
        disc = np.zeros_like(bike_mask, dtype=np.uint8)
        cv2.circle(disc, (px, py), int(1.25 * r_exp), 255, -1)
        region = cv2.bitwise_and(bike_mask, disc)
        cv2.circle(taken.view(np.uint8), (px, py), int(1.4 * r_exp), 1, -1)
        cnts = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        if not cnts:
            continue
        cnt = max(cnts, key=cv2.contourArea)
        area = float(cv2.contourArea(cnt))
        if len(cnt) < 8 or area < 0.6 * math.pi * r_in * r_in:
            continue
        (cx, cy), (a, b), ang = cv2.fitEllipse(cnt)
        major, minor = max(a, b), min(a, b)
        approx = False
        if minor < 4 or major / max(minor, 1e-6) > 5.0:
            continue
        if major > 0.85 * box_h or minor > 2.6 * r_in * 1.6:
            # the fit ran off along attached frame/leg; fall back to the
            # inscribed circle, which the disc cannot inflate
            cx, cy, major, minor, ang, approx = float(px), float(py), 2.6 * r_in, 2.0 * r_in, 90.0, True
        fill = area / max(math.pi * major * minor / 4, 1.0)
        if fill < 0.45 and not approx:
            continue
        blobs.append({"cx": float(cx), "cy": float(cy), "major": float(major),
                      "minor": float(minor), "angle": float(ang), "area": float(area),
                      "r_inscribed": r_in, "approx": approx, "contour": cnt})
    return blobs


def _hough_wheels(frame_bgr, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    crop = frame_bgr[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return []
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.medianBlur(g, 5)
    h = y2 - y1
    circles = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=max(10, h * 0.3),
                               param1=120, param2=28,
                               minRadius=max(6, int(h * 0.12)), maxRadius=max(8, int(h * 0.4)))
    out = []
    if circles is not None:
        for cx, cy, r in circles[0][:2]:
            out.append({"cx": float(cx + x1), "cy": float(cy + y1), "major": float(2 * r),
                        "minor": float(2 * r), "angle": 0.0, "area": float(math.pi * r * r),
                        "contour": None, "hough": True})
    return out


def _pt(kps, *names):
    pts = [kps[n][:2] for n in names if n in kps and kps[n][2] > 0.3]
    return np.mean(pts, axis=0) if pts else None


def _approx_wheel(cx, cy, r):
    """A wheel placed at a model axle when no ellipse could be fitted there."""
    return {"cx": float(cx), "cy": float(cy), "major": 2.0 * r, "minor": 2.0 * r,
            "angle": 0.0, "area": math.pi * r * r, "approx": True, "from_axle": True}


def _axles(bike_kps: dict | None, min_conf: float = 0.5):
    if not bike_kps:
        return None
    fa, ra = bike_kps.get("front_axle"), bike_kps.get("rear_axle")
    if fa and ra and fa[2] >= min_conf and ra[2] >= min_conf:
        return np.array(fa[:2], float), np.array(ra[:2], float)
    return None


def find_wheels(frame_bgr, bike_mask, bike_box, kps: dict, prev: dict | None = None,
                bike_kps: dict | None = None):
    """Return {"front": wheel|None, "rear": wheel|None, "method": str}.

    When the DH bike model supplies confident front/rear axle keypoints they
    decide which wheel is which (its front/rear naming is reliable across
    views, unlike the hands-over-front heuristic in quarter views) and stand
    in for a wheel no ellipse could be fitted to (flagged approx).
    """
    if bike_box is None:
        return {"front": None, "rear": None, "method": "no_bike"}
    axles = _axles(bike_kps)
    box_h = max(bike_box[3] - bike_box[1], 1.0)
    blobs = _wheel_blobs(bike_mask, box_h) if bike_mask is not None else []
    method = "mask"
    if len(blobs) < 2:
        blobs = blobs + _hough_wheels(frame_bgr, bike_box)
        method = "mask+hough" if blobs else "none"
    if axles is not None:
        fa, ra = axles
        wb = float(np.linalg.norm(fa - ra))
        r_prev = [prev[k]["radius_px"] for k in ("front", "rear") if prev and prev.get(k)]
        # radius: last frame's wheels if we had them, else ~0.3 wheelbase (29" DH bike)
        r_est = float(np.mean(r_prev)) if r_prev else 0.3 * wb
        if wb >= 20.0 and r_est >= 6.0:
            pool = sorted(blobs, key=lambda b: -b["area"])[:4]
            out, used, n_fit = {}, set(), 0
            for label, ax in (("front", fa), ("rear", ra)):
                pick = None
                for i, b in enumerate(pool):
                    if i in used:
                        continue
                    d = math.hypot(b["cx"] - ax[0], b["cy"] - ax[1])
                    if d < 0.7 * max(r_est, b["major"] / 2) and (pick is None or d < pick[0]):
                        pick = (d, i)
                if pick is not None:
                    used.add(pick[1]); out[label] = pool[pick[1]]; n_fit += 1
                else:
                    out[label] = _approx_wheel(ax[0], ax[1], r_est)
            m = ("kp_only" if n_fit == 0 else f"{method}+kp" if blobs else "kp")
            return {"front": _pack(out["front"]), "rear": _pack(out["rear"]), "method": m}
    if not blobs:
        return {"front": None, "rear": None, "method": method}
    blobs = sorted(blobs, key=lambda b: -b["area"])[:3]

    wrist, ankle = _pt(kps, "l_wrist", "r_wrist"), _pt(kps, "l_ankle", "r_ankle")
    # which way is the rider facing? face visible = coming at the camera
    nose_c = kps.get("nose", [0, 0, 0])[2] if "nose" in kps else 0.0
    facing_camera = nose_c > 0.5

    def assign(two):
        a, b = two
        # temporal continuity first: keep the labels of the wheels we tracked
        # a frame ago when both candidates sit near their previous positions
        if prev and prev.get("front") and prev.get("rear"):
            pf, pr = prev["front"], prev["rear"]
            tol = 0.6 * max(pf["radius_px"], pr["radius_px"])
            def near(w, p): return math.hypot(w["cx"] - p["cx"], w["cy"] - p["cy"]) < tol
            if near(a, pf) and near(b, pr):
                return (a, b)
            if near(b, pf) and near(a, pr):
                return (b, a)
        d = math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"])
        dia = (a["major"] + b["major"]) / 2
        # hands sit over the front wheel, feet over the rear: decisive whenever
        # the two wheels are separated enough in the image for it to mean anything
        if wrist is not None and ankle is not None:
            da = math.hypot(a["cx"] - wrist[0], a["cy"] - wrist[1]) - math.hypot(a["cx"] - ankle[0], a["cy"] - ankle[1])
            db = math.hypot(b["cx"] - wrist[0], b["cy"] - wrist[1]) - math.hypot(b["cx"] - ankle[0], b["cy"] - ankle[1])
            if abs(da - db) > 0.25 * dia:
                return (a, b) if da < db else (b, a)          # nearer the hands = front
        # truly end-on (wheels stacked along the line of sight, both thin): the
        # bigger one is nearer the camera; from behind, nearer = rear
        thin = min(a["minor"] / max(a["major"], 1e-6), b["minor"] / max(b["major"], 1e-6)) < 0.55
        if d < 0.8 * dia and thin:
            near, far = (a, b) if a["major"] >= b["major"] else (b, a)
            return (near, far) if facing_camera else (far, near)
        if prev and prev.get("front") and prev.get("rear"):
            pf = prev["front"]
            da = math.hypot(a["cx"] - pf["cx"], a["cy"] - pf["cy"])
            db = math.hypot(b["cx"] - pf["cx"], b["cy"] - pf["cy"])
            return (a, b) if da < db else (b, a)
        return (a, b) if a["cy"] < b["cy"] else (b, a)

    if len(blobs) >= 2:
        # choose the pair with the most plausible wheelbase (1.2..2.6 diameters apart)
        best = None
        for i in range(len(blobs)):
            for j in range(i + 1, len(blobs)):
                p, q = blobs[i], blobs[j]
                d = math.hypot(p["cx"] - q["cx"], p["cy"] - q["cy"])
                dia = (p["major"] + q["major"]) / 2
                ratio = d / max(dia, 1e-6)
                score = -abs(ratio - 1.7) + 0.5 * min(p["area"], q["area"]) / max(p["area"], q["area"])
                if 0.15 <= ratio <= 2.8 and (best is None or score > best[0]):
                    best = (score, p, q)
        if best:
            front, rear = assign((best[1], best[2]))
            return {"front": _pack(front), "rear": _pack(rear), "method": method}
    w = blobs[0]
    # single wheel: label by proximity to hands vs feet, else keep previous label
    label = "rear"
    if wrist is not None and ankle is not None:
        label = "front" if math.hypot(w["cx"] - wrist[0], w["cy"] - wrist[1]) < math.hypot(w["cx"] - ankle[0], w["cy"] - ankle[1]) else "rear"
    out = {"front": None, "rear": None, "method": method + "/single"}
    out[label] = _pack(w)
    return out


def _pack(w):
    tilt = w["angle"]                      # cv2 ellipse angle: major axis from x-axis, deg
    inplane = ((tilt + 90) % 180) - 90     # major-axis angle relative to vertical, (-90, 90]
    # a near-circular ellipse has no defined major axis: its tilt is noise, not roll
    if w["minor"] / max(w["major"], 1e-6) > 0.85:
        inplane = None
    # lowest image point of the ellipse: a semi-axis along the steepest direction
    th = math.radians(w["angle"]); a, b = w["major"] / 2, w["minor"] / 2
    drop = math.sqrt((a * math.sin(th)) ** 2 + (b * math.cos(th)) ** 2)
    return {"cx": round(w["cx"], 1), "cy": round(w["cy"], 1),
            "major_px": round(w["major"], 1), "minor_px": round(w["minor"], 1),
            "radius_px": round(w["major"] / 2, 1),
            "inplane_tilt_deg": round(inplane, 1) if inplane is not None else None,
            "outplane_deg": round(math.degrees(math.acos(min(1.0, w["minor"] / max(w["major"], 1e-6)))), 1),
            "bottom_y": round(w["cy"] + drop, 1),
            "hough": bool(w.get("hough", False)), "approx": bool(w.get("approx", False)),
            "from_axle": bool(w.get("from_axle", False))}


# ------------------------------------------------------ contact heuristic

def contact_score(frame_gray, prev_gray, wheel: dict, axle_vel: tuple[float, float] | None) -> dict:
    """Ground-contact evidence for one wheel: texture under the tyre and
    motion agreement between tyre bottom and the ground right below it."""
    h, w = frame_gray.shape
    r = wheel["radius_px"]
    bx, by = wheel["cx"], wheel.get("bottom_y", wheel["cy"] + wheel["minor_px"] / 2)
    band = max(3, int(0.12 * r))
    y0, y1 = int(by + 1), int(min(h, by + 1 + band))
    x0, x1 = int(max(0, bx - 0.5 * r)), int(min(w, bx + 0.5 * r))
    if y1 <= y0 + 1 or x1 <= x0 + 3:
        return {"score": None, "state": "unknown"}
    ground = frame_gray[y0:y1, x0:x1]
    tex = float(np.std(ground)) / 32.0
    texture = float(np.clip(tex, 0, 1))

    agree = None
    if prev_gray is not None and axle_vel is not None:
        try:
            ty0, ty1 = int(max(0, by - band)), int(by)
            flow_g = cv2.calcOpticalFlowFarneback(prev_gray[y0:y1, x0:x1], ground, None,
                                                  0.5, 2, 9, 2, 5, 1.1, 0)
            tire = frame_gray[ty0:ty1, x0:x1]
            flow_t = cv2.calcOpticalFlowFarneback(prev_gray[ty0:ty1, x0:x1], tire, None,
                                                  0.5, 2, 9, 2, 5, 1.1, 0)
            vg = flow_g.reshape(-1, 2).mean(axis=0)
            vt = flow_t.reshape(-1, 2).mean(axis=0)
            diff = float(np.hypot(*(vg - vt)))
            agree = float(np.clip(1.0 - diff / max(0.25 * r, 2.0), 0, 1))
        except cv2.error:
            agree = None
    score = texture if agree is None else 0.4 * texture + 0.6 * agree
    state = "contact" if score >= 0.55 else ("airborne" if score <= 0.3 else "uncertain")
    return {"score": round(score, 2), "texture": round(texture, 2),
            "flow_agreement": round(agree, 2) if agree is not None else None, "state": state}


# --------------------------------------------------------- per-run series

def wheel_series(track_frames: list[dict], fps: float, specs: dict | None = None) -> dict:
    """Derive bike-level attitude, travel and deflection series from the
    per-frame `wheels` records already attached by the tracker. Mutates
    each frame (adds `bike_geom`) and returns a run summary."""
    specs = specs or {}
    od_f, od_r = specs.get("tire_od_front_mm"), specs.get("tire_od_rear_mm")
    fork_t, rear_t = specs.get("fork_travel_mm"), specs.get("rear_travel_mm")

    n = len(track_frames)
    fx = np.full(n, np.nan); fy = np.full(n, np.nan); rx = np.full(n, np.nan); ry = np.full(n, np.nan)
    fr = np.full(n, np.nan); rr = np.full(n, np.nan); cxs = np.full(n, np.nan); cys = np.full(n, np.nan)
    fork_d = np.full(n, np.nan); rear_d = np.full(n, np.nan); mmpp = np.full(n, np.nan)

    for i, f in enumerate(track_frames):
        wh = f.get("wheels") or {}
        kps = f.get("keypoints", {})
        F, R = wh.get("front"), wh.get("rear")
        scale = []
        # axle-placed wheels have a guessed radius: use them for position,
        # never for the mm/px scale
        if F:
            fx[i], fy[i], fr[i] = F["cx"], F["cy"], F["radius_px"]
            if od_f and not F.get("from_axle"): scale.append(od_f / max(F["major_px"], 1e-6))
        if R:
            rx[i], ry[i], rr[i] = R["cx"], R["cy"], R["radius_px"]
            if od_r and not R.get("from_axle"): scale.append(od_r / max(R["major_px"], 1e-6))
        if scale:
            mmpp[i] = float(np.mean(scale))
        c = f.get("bike_box")
        if c:
            cxs[i], cys[i] = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        wrist, ankle = _pt(kps, "l_wrist", "r_wrist"), _pt(kps, "l_ankle", "r_ankle")
        if F and wrist is not None:
            fork_d[i] = math.hypot(F["cx"] - wrist[0], F["cy"] - wrist[1])
        if R and ankle is not None:
            rear_d[i] = math.hypot(R["cx"] - ankle[0], R["cy"] - ankle[1])

    # attitude from the axle line
    both = ~np.isnan(fx) & ~np.isnan(rx)
    axle_ang = np.full(n, np.nan); wb_px = np.full(n, np.nan); yaw = np.full(n, np.nan)
    axle_ang[both] = np.degrees(np.arctan2(-(fy[both] - ry[both]), fx[both] - rx[both]))
    wb_px[both] = np.hypot(fx[both] - rx[both], fy[both] - ry[both])
    dia = np.nanmean(np.stack([fr, rr]), axis=0) * 2
    yaw[both] = np.clip(wb_px[both] / np.maximum(dia[both], 1e-6) / 1.7, 0, 1.2)

    # travel: compression = extended baseline minus current sprung-unsprung
    # distance, in wheel radii (scale-free), then px. The baseline is a
    # rolling 90th percentile over +-1.5 s so a camera that zooms through the
    # run does not read as travel, and compression is capped at the bike's
    # travel: anything beyond that is a label swap or a bad keypoint, not
    # suspension, and is dropped.
    def travel(d, r, cap_mm):
        out = np.full(n, np.nan)
        ok = ~np.isnan(d) & ~np.isnan(r) & (r > 0)
        if ok.sum() < 5:
            return out
        norm = np.where(ok, d / np.where(ok, r, 1.0), np.nan)
        half = max(2, int(1.5 * fps))
        for i in np.where(ok)[0]:
            seg = norm[max(0, i - half): i + half + 1]
            seg = seg[~np.isnan(seg)]
            if len(seg) < 3:
                continue
            comp_px = (float(np.percentile(seg, 90)) - norm[i]) * r[i]
            if comp_px < 0:
                comp_px = 0.0
            if cap_mm and not np.isnan(mmpp[i]) and comp_px * mmpp[i] > 1.25 * cap_mm:
                continue
            out[i] = comp_px
        return out
    fork_px = travel(fork_d, fr, fork_t)
    rear_px = travel(rear_d, rr, rear_t)

    # deflection: fast axle motion relative to the bike box centre
    win = max(3, int(fps / 2) | 1)
    def highpass(x):
        x = _fill(x)
        k = np.ones(win) / win
        slow = np.convolve(np.pad(x, win // 2, mode="edge"), k, mode="valid")[: len(x)]
        return x - slow
    fdy = highpass(fy - cys) if both.any() else np.zeros(n)
    rdy = highpass(ry - cys) if both.any() else np.zeros(n)
    fdx = highpass(fx - cxs) if both.any() else np.zeros(n)
    rdx = highpass(rx - cxs) if both.any() else np.zeros(n)

    mm = _fill(mmpp) if (~np.isnan(mmpp)).any() else np.full(n, np.nan)
    # wheel tilt relative to the rider's torso: camera-roll-invariant (an FPV
    # drone banks through turns, so tilt vs image vertical includes the camera)
    torso = np.array([(f.get("attitude") or {}).get("torso_tilt_deg") if (f.get("attitude") or {}).get("torso_tilt_deg") is not None else np.nan for f in track_frames], float)
    rel_roll = {}
    for side in ("front", "rear"):
        tilt = np.array([((f.get("wheels") or {}).get(side) or {}).get("inplane_tilt_deg") if ((f.get("wheels") or {}).get(side) or {}).get("inplane_tilt_deg") is not None else np.nan for f in track_frames], float)
        rel_roll[side] = tilt - torso
    for i, f in enumerate(track_frames):
        g = {"axle_line_deg": _r(axle_ang[i]), "wheelbase_px": _r(wb_px[i]),
             "yaw_proxy": _r(yaw[i], 3), "mm_per_px": _r(mm[i], 3),
             "fork_comp_px": _r(fork_px[i]), "rear_comp_px": _r(rear_px[i]),
             "fork_comp_mm": _r(fork_px[i] * mm[i]) if not np.isnan(mm[i]) else None,
             "rear_comp_mm": _r(rear_px[i] * mm[i]) if not np.isnan(mm[i]) else None,
             "front_defl_v_px": _r(fdy[i]), "rear_defl_v_px": _r(rdy[i]),
             "front_defl_lat_px": _r(fdx[i]), "rear_defl_lat_px": _r(rdx[i]),
             "front_roll_vs_torso_deg": _r(rel_roll["front"][i]), "rear_roll_vs_torso_deg": _r(rel_roll["rear"][i])}
        if fork_t and g["fork_comp_mm"] is not None:
            g["fork_comp_pct"] = _r(100 * min(g["fork_comp_mm"], fork_t) / fork_t)
        if rear_t and g["rear_comp_mm"] is not None:
            g["rear_comp_pct"] = _r(100 * min(g["rear_comp_mm"], rear_t) / rear_t)
        f["bike_geom"] = g

    view = [f.get("attitude", {}).get("view") for f in track_frames]
    side = sum(v == "side" for v in view); comp = sum(v == "compact" for v in view)
    dominant = "side" if side > comp else ("compact" if comp else "unknown")
    def stat(x, mmv=None):
        v = x[~np.isnan(x)]
        if len(v) == 0:
            return None
        d = {"mean": _r(float(v.mean())), "p95": _r(float(np.percentile(v, 95))), "max": _r(float(v.max()))}
        return d
    scale_med = float(np.nanmedian(mmpp)) if (~np.isnan(mmpp)).any() else None
    # noise floor from the data: the median frame-to-frame jump of the axle
    # centres relative to the bike box is fit jitter, not the wheel moving
    # (a wheel cannot move a large fraction of its radius in one frame)
    jumps = []
    for x, c in ((fx, cxs), (fy, cys), (rx, cxs), (ry, cys)):
        rel = x - c
        d = np.abs(np.diff(rel))
        jumps += list(d[~np.isnan(d)])
    jitter_px = float(np.median(jumps)) if jumps else 5.0
    noise_mm = jitter_px * scale_med if scale_med else None
    def rms_mm(x):
        if not scale_med:
            return None
        v = float(np.sqrt(np.nanmean((x * mm) ** 2)))
        return {"rms_mm": _r(v), "at_noise_floor": bool(v < 2 * noise_mm)}
    summary = {
        "coverage": {"front": _r(float(np.mean(~np.isnan(fx))), 2), "rear": _r(float(np.mean(~np.isnan(rx))), 2),
                     "both": _r(float(both.mean()), 2)},
        "scale_mm_per_px": _r(scale_med, 3) if scale_med else None,
        "noise_floor_mm": _r(noise_mm) if noise_mm else None,
        "axle_jitter_px": _r(jitter_px),
        "travel_note": ("compression readings that reach the 1.25x-travel cap mean the axle-to-bar / axle-to-pedal "
                        "distance is jittering by about a wheel radius: at that point travel is a bounded proxy, "
                        "not a measurement -- needs closer or sharper footage"),
        "travel_saturated": bool(
            (fork_t and (~np.isnan(fork_px)).any() and scale_med and float(np.nanpercentile(fork_px * mm, 95)) >= fork_t) or
            (rear_t and (~np.isnan(rear_px)).any() and scale_med and float(np.nanpercentile(rear_px * mm, 95)) >= rear_t)),
        "axle_line_deg": stat(axle_ang),
        "axle_line_means": ("pitch" if dominant == "side" else "roll" if dominant == "compact" else "pitch-or-roll (view unknown)"),
        "yaw_proxy": stat(yaw),
        "fork_comp_mm": stat(fork_px * mm), "rear_comp_mm": stat(rear_px * mm),
        "fork_comp_pct_of_travel": _r(100 * float(np.nanpercentile(fork_px * mm, 95)) / fork_t) if fork_t and (~np.isnan(fork_px)).any() and (~np.isnan(mm)).any() else None,
        "rear_comp_pct_of_travel": _r(100 * float(np.nanpercentile(rear_px * mm, 95)) / rear_t) if rear_t and (~np.isnan(rear_px)).any() and (~np.isnan(mm)).any() else None,
        "front_defl_v": rms_mm(fdy), "rear_defl_v": rms_mm(rdy),
        "front_defl_lat": rms_mm(fdx), "rear_defl_lat": rms_mm(rdx),
        "wheel_roll": {
            "front_vs_image_vertical_deg": stat(np.abs(np.array([((f.get("wheels") or {}).get("front") or {}).get("inplane_tilt_deg") if ((f.get("wheels") or {}).get("front") or {}).get("inplane_tilt_deg") is not None else np.nan for f in track_frames], float))),
            "rear_vs_image_vertical_deg": stat(np.abs(np.array([((f.get("wheels") or {}).get("rear") or {}).get("inplane_tilt_deg") if ((f.get("wheels") or {}).get("rear") or {}).get("inplane_tilt_deg") is not None else np.nan for f in track_frames], float))),
            "front_vs_torso_deg": stat(np.abs(rel_roll["front"])),
            "rear_vs_torso_deg": stat(np.abs(rel_roll["rear"])),
            "note": ("in-plane tilt of the wheel ellipse. vs image vertical includes camera roll (FPV drones bank); "
                     "vs torso is the bike-lean/body-lean separation, camera-invariant. Undefined (None) when the "
                     "wheel is seen near face-on; roll in rear/chase views, steering/yaw in side views")},
        "contact": _contact_summary(track_frames),
        "note": ("travel = sprung-unsprung distance change from the run's own extended baseline (95th pct); "
                 "mm via wheel-diameter scale from data/bike_specs.yaml; heuristics, not sensor data"),
    }
    return summary


def kp_travel_series(track_frames: list[dict], fps: float, specs: dict | None = None,
                     window_s: float = 0.25, baseline_pct: float = 90.0, max_gap: int = 6,
                     min_seg_s: float = 0.6, min_conf: float = 0.5, side_only: bool = True) -> dict:
    """Fork and rear-suspension travel from the DH bike keypoints, the way
    the mtbkin project measures it:

        fork_len  = |fork_crown - front_axle|     shrinks as the fork compresses
        rear_len  = |bottom_bracket - rear_axle|  shrinks as the rear compresses
                    (straight-line BB-to-axle, which moves ~1/3 of the wheel's
                    travel on a typical DH linkage; reported as rear-centre
                    delta, not as travel)
        wheelbase = |front_axle - rear_axle|

    The series is cut into segments at gaps and at shot changes (wheelbase
    jumping > 30% between consecutive frames). Inside a segment the scale
    is CONSTANT: the bike's known wheelbase over the 97th-percentile
    wheelbase in px (i.e. at full extension, before the fork shortens it),
    so image scale cancels and fork motion cannot leak into rear metrics.
    Lengths are Savitzky-Golay smoothed (~0.15 s) before the extended
    baseline (97th pct) is subtracted. Static sag is unknown from video, so
    "travel" is compression from the run's most-extended state.
    Mutates `bike_geom` in each frame; returns a summary."""
    from scipy.signal import savgol_filter
    specs = specs or {}
    wb_mm = float(specs.get("wheelbase_mm") or 1250.0)
    fork_t, rear_t = specs.get("fork_travel_mm"), specs.get("rear_travel_mm")
    n = len(track_frames)
    P = {k: np.full((n, 2), np.nan) for k in ("front_axle", "rear_axle", "fork_crown", "bottom_bracket")}
    n_side = 0
    for i, f in enumerate(track_frames):
        # a fork foreshortens differently from the wheelbase in rear/quarter views, so the
        # length ratio drifts with viewing angle; only side views measure travel
        view = (f.get("attitude") or {}).get("view")
        if side_only and view not in (None, "side"):
            continue
        n_side += 1
        for k, v in (f.get("bike_kps") or {}).items():
            if k in P and v[2] >= min_conf:
                P[k][i] = v[:2]
    def dist(a, b):
        return np.hypot(P[a][:, 0] - P[b][:, 0], P[a][:, 1] - P[b][:, 1])
    fork_len, rear_len, wb = dist("fork_crown", "front_axle"), dist("bottom_bracket", "rear_axle"), dist("front_axle", "rear_axle")

    # segments over frames with a wheelbase
    valid = ~np.isnan(wb)
    segs, start, last = [], None, None
    for i in range(n):
        if valid[i]:
            if start is None:
                start = i
            elif (i - last > max_gap) or abs(wb[i] - wb[last]) > 0.3 * wb[last]:
                segs.append((start, last)); start = i
            last = i
    if start is not None:
        segs.append((start, last))
    segs = [(a, b) for a, b in segs if (b - a + 1) / fps >= min_seg_s]

    def smooth(x):
        idx = np.arange(len(x)); ok = ~np.isnan(x)
        if ok.sum() < 5:
            return np.full_like(x, np.nan)
        y = np.interp(idx, idx[ok], x[ok])
        win = max(5, int(window_s * fps) | 1)
        win = min(win, len(y) if len(y) % 2 else len(y) - 1)
        if win < 5:
            return y
        return savgol_filter(y, win, 2)

    fork_mm = np.full(n, np.nan); rear_mm = np.full(n, np.nan); seg_id = np.full(n, -1); scale_seg = np.full(n, np.nan)
    noise_mm = []; n_bad = 0; n_all = 0
    for si, (a, b) in enumerate(segs):
        sl = slice(a, b + 1)
        wb_s = wb[sl]
        scale = wb_mm / float(np.nanpercentile(wb_s, 97))
        scale_seg[sl] = scale; seg_id[sl] = si
        for arr, out, cap in ((fork_len, fork_mm, fork_t), (rear_len, rear_mm, None)):
            raw = arr[sl]
            if (~np.isnan(raw)).sum() < 5:
                continue
            sm = smooth(raw)
            base = float(np.nanpercentile(sm, baseline_pct))
            t = (base - sm) * scale
            if cap:
                bad = (t < -30) | (t > 1.25 * cap)
                n_bad += int(bad.sum()); n_all += int((~np.isnan(t)).sum())
                t[bad] = np.nan
            else:
                t[np.abs(t) > 150] = np.nan
            out[sl] = t
            d = np.abs(np.diff((raw - sm))) * scale
            noise_mm += list(d[~np.isnan(d)])
    for i, f in enumerate(track_frames):
        g = f.setdefault("bike_geom", {})
        g["fork_travel_kp_mm"] = _r(fork_mm[i]); g["rear_center_delta_kp_mm"] = _r(rear_mm[i])
        g["wheelbase_kp_px"] = _r(wb[i]); g["kp_segment"] = int(seg_id[i]); g["kp_scale_mm_per_px"] = _r(scale_seg[i], 3)

    def stat(x):
        v = x[~np.isnan(x)]
        return {"p50": _r(float(np.percentile(v, 50))), "p95": _r(float(np.percentile(v, 95))), "max": _r(float(v.max()))} if len(v) else None
    # compression events: local maxima of fork travel above 30% of travel, >= 0.3 s apart
    events = []
    if fork_t and (~np.isnan(fork_mm)).any():
        x = np.where(np.isnan(fork_mm), -1e9, fork_mm); gap = max(1, int(0.3 * fps))
        for i in range(1, n - 1):
            if x[i] >= 0.3 * fork_t and x[i] >= x[max(0, i - gap): i + gap + 1].max():
                events.append({"t_s": _r(i / fps, 2), "fork_travel_mm": _r(x[i]), "pct": _r(100 * x[i] / fork_t)})
    return {
        "coverage": _r(float(np.mean(~np.isnan(fork_mm))), 2),
        "side_view_frames": _r(n_side / max(n, 1), 2),
        "out_of_range_dropped": _r(n_bad / n_all, 2) if n_all else None,
        "segments": len(segs),
        "fork_travel_mm": stat(fork_mm), "rear_center_delta_mm": stat(rear_mm),
        "fork_travel_pct_p95": _r(100 * float(np.nanpercentile(fork_mm, 95)) / fork_t) if fork_t and (~np.isnan(fork_mm)).any() else None,
        "noise_floor_mm": _r(float(np.median(noise_mm))) if noise_mm else None,
        "compression_events": events[:20], "n_events": len(events),
        "note": ("crown-to-axle (fork) and BB-to-rear-axle (rear centre) lengths from the DH bike keypoints, scaled by "
                 "the known wheelbase at full extension per segment; compression relative to the segment's 97th-pct "
                 "extended state, sag unknown. noise_floor_mm = median frame-to-frame residual after smoothing: travel "
                 "readings below ~2x it are jitter, not suspension"),
    }


def _contact_summary(frames):
    out = {}
    for side in ("front", "rear"):
        states = [((f.get("contact") or {}).get(side) or {}).get("state") for f in frames]
        known = [s for s in states if s and s != "unknown"]
        if not known:
            out[side] = None
            continue
        out[side] = {s: round(known.count(s) / len(known), 2) for s in ("contact", "uncertain", "airborne")}
    # airborne windows (both wheels)
    air, start = [], None
    for i, f in enumerate(frames + [{}]):
        c = f.get("contact") or {}
        a = all(((c.get(s) or {}).get("state") == "airborne") for s in ("front", "rear")) and c
        if a and start is None:
            start = i
        elif not a and start is not None:
            if i - start >= 3:
                air.append({"start_s": round(frames[start]["time_s"], 2), "end_s": round(frames[i - 1]["time_s"], 2)})
            start = None
    out["airborne_windows"] = air
    return out


def _fill(x):
    x = np.array(x, dtype=float)
    nans = np.isnan(x)
    if nans.all():
        return np.zeros_like(x)
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def _r(v, nd=1):
    try:
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), nd)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------- overlay

def draw_wheels(frame, rec: dict):
    """Draw wheel ellipses, axle line, contact state and travel readouts."""
    wh = rec.get("wheels") or {}
    geom = rec.get("bike_geom") or {}
    con = rec.get("contact") or {}
    tire = rec.get("tire") or {}
    pts = {}
    for side, col in (("front", (60, 200, 255)), ("rear", (255, 160, 60))):
        w = wh.get(side)
        if not w:
            continue
        st = (con.get(side) or {}).get("state", "unknown")
        color = (60, 220, 60) if st == "contact" else (40, 40, 240) if st == "airborne" else col
        cv2.ellipse(frame, (int(w["cx"]), int(w["cy"])), (int(w["major_px"] / 2), int(w["minor_px"] / 2)),
                    (w.get("inplane_tilt_deg") or 0.0) + 90, 0, 360, color, 2, cv2.LINE_AA)
        cv2.circle(frame, (int(w["cx"]), int(w["cy"])), 3, color, -1)
        pts[side] = (int(w["cx"]), int(w["cy"]))
        t = (tire.get(side) or {})
        label = f"{side[0].upper()} {st}"
        if t.get("state") and t["state"] not in ("unknown", st):
            label += f" {t['state']}"
        if t.get("slip_ratio") is not None:
            label += f" k={t['slip_ratio']:+.2f}"
        if t.get("slip_angle_deg") is not None:
            label += f" a={t['slip_angle_deg']:+.0f}"
        cv2.putText(frame, label, (int(w["cx"] - w["radius_px"]), int(w["cy"] + w["radius_px"] + 16)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    if "front" in pts and "rear" in pts:
        cv2.line(frame, pts["front"], pts["rear"], (200, 200, 200), 1, cv2.LINE_AA)
    y = 24 + 22 * 9
    lines = []
    if geom.get("fork_comp_mm") is not None:
        lines.append(f"fork {geom['fork_comp_mm']:.0f}mm" + (f" ({geom.get('fork_comp_pct', 0):.0f}%)" if geom.get("fork_comp_pct") is not None else ""))
    if geom.get("rear_comp_mm") is not None:
        lines.append(f"shock {geom['rear_comp_mm']:.0f}mm" + (f" ({geom.get('rear_comp_pct', 0):.0f}%)" if geom.get("rear_comp_pct") is not None else ""))
    if geom.get("axle_line_deg") is not None:
        lines.append(f"axle line {geom['axle_line_deg']:+.0f} deg  yaw {geom.get('yaw_proxy', 0):.2f}")
    for ln in lines:
        cv2.putText(frame, ln, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 20
    return frame
