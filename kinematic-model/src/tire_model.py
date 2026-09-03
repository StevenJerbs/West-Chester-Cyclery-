"""Tyre traction model: slip ratio, slip angle, camber and a Magic-Formula
grip envelope, estimated from video, with the envelope refined from the
corpus of tracked runs.

Where the idea comes from. Sim-racing tyre models (the Pacejka "Magic
Formula" used in Assetto Corsa, the brush-model derivatives in Codemasters'
DiRT Rally, rFactor 2's TGM) all reduce to the same three inputs per wheel:

    kappa  -- longitudinal slip ratio  (wheel speed vs ground speed)
    alpha  -- slip angle               (where the tyre points vs where it goes)
    gamma  -- camber                   (lean of the wheel plane)

and one output family: normalised force (F / Fz) as a curve that rises
roughly linearly, peaks, then falls off -- the fall-off is the loss of
traction. Loose surfaces (gravel, dirt) have a lower, broader, later peak
than tarmac and a gentler drop, which is why a rally car can live at 10-15%
slip. The "Magic Formula":

    y(x) = D * sin(C * atan(B*x - E*(B*x - atan(B*x))))

with (B, C, D, E) per axis. Combined slip uses the friction ellipse: the
tyre has one grip budget, spent between braking/driving and cornering.

What we can and cannot get from a single camera. We cannot measure forces.
We *can* measure the three inputs per wheel, as image-plane proxies:

  kappa  from the wheel's rotation rate (optical flow around the rim, only
         when the wheel is seen obliquely enough to show rotation) against
         the ground's speed past the axle (ground flow relative to the axle's
         own image motion, so a moving camera cancels out);
  alpha  from the direction of the ground's motion past the contact patch
         relative to the wheel plane;
  gamma  from wheels.py's in-plane ellipse tilt (rear/chase views).

From those the model reports, per wheel per frame, where the tyre sits on
its grip curve (utilisation 0..1, >1 = past the peak) and a state:

    grip | limit | sliding | locked | spinning | airborne | unknown

"locked" is a braking lock-up: ground moving, wheel not rotating. "sliding"
is combined slip past the peak -- the lateral-loading loss of traction.

Training. Without force ground truth, what the corpus can teach is the
envelope: pooled |kappa| and |alpha| from advanced riders' clean runs give
the operating band pros hold (their 90th percentile becomes the "limit"
threshold), and windows leading into labelled crashes (data/crashes.yaml)
give the sliding side. fit_envelope() writes weights/tire_model_vNNN.json;
the defaults below are the rally-sim loose-surface starting point used
until enough runs carry tyre data.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = ROOT / "weights"

# Loose-surface Magic Formula defaults (DH tyre on dirt). Peak longitudinal
# ~0.18 slip, peak lateral ~9 deg -- rally-sim gravel territory.
DEFAULT_ENVELOPE = {
    "longitudinal": {"B": 7.0, "C": 1.65, "D": 0.85, "E": 0.35, "peak_kappa": 0.18},
    "lateral":      {"B": 6.5, "C": 1.35, "D": 0.80, "E": -0.8, "peak_alpha_deg": 9.0},
    "camber_thrust_per_deg": 0.006,   # small added lateral grip from lean, per degree
    "limit_fraction": 0.85,            # utilisation above this = "limit"
    "min_ground_speed_px_s": 40.0,     # below this no slip estimate is meaningful
    "source": "rally-sim loose-surface defaults; not yet fitted to this corpus",
}


def magic_formula(x, B, C, D, E):
    bx = B * x
    return D * np.sin(C * np.arctan(bx - E * (bx - np.arctan(bx))))


def _latest_envelope_path():
    if WEIGHTS_DIR.exists():
        w = sorted(WEIGHTS_DIR.glob("tire_model_v*.json"))
        if w:
            return w[-1]
    return None


def load_envelope() -> dict:
    p = _latest_envelope_path()
    if p:
        env = json.loads(p.read_text())
        env["_path"] = str(p)
        return env
    return dict(DEFAULT_ENVELOPE)


# ---------------------------------------------------------- per-frame slip

def _rim_rotation(prev_gray, gray, wheel) -> float | None:
    """Wheel rotation rate in the image plane, rad/frame, from optical flow
    in the annulus 0.5R..0.95R. Sign: positive = clockwise on screen.
    Returns None when the wheel is too end-on for rotation to show."""
    if wheel["minor_px"] / max(wheel["major_px"], 1e-6) < 0.6:
        return None
    r = wheel["radius_px"]
    if r < 8:
        return None
    cx, cy = wheel["cx"], wheel["cy"]
    x0, y0 = int(max(0, cx - r - 2)), int(max(0, cy - r - 2))
    x1, y1 = int(min(gray.shape[1], cx + r + 3)), int(min(gray.shape[0], cy + r + 3))
    if x1 - x0 < 12 or y1 - y0 < 12:
        return None
    # a smeared rim (spokes/tread blurred into a ring) reads as a slow wheel:
    # refuse rather than report a false lock-up
    if float(cv2.Laplacian(gray[y0:y1, x0:x1], cv2.CV_64F).var()) < SHARPNESS_MIN:
        return None
    try:
        flow = cv2.calcOpticalFlowFarneback(prev_gray[y0:y1, x0:x1], gray[y0:y1, x0:x1], None,
                                            0.5, 3, max(7, int(r / 3)), 3, 5, 1.2, 0)
    except cv2.error:
        return None
    ys, xs = np.mgrid[y0:y1, x0:x1]
    dx, dy = xs - cx, ys - cy
    rho = np.hypot(dx, dy)
    ann = (rho > 0.5 * r) & (rho < 0.95 * r)
    if ann.sum() < 20:
        return None
    # tangential unit vector for clockwise rotation on screen (y down): (-dy, dx)/rho
    tx, ty = -dy[ann] / rho[ann], dx[ann] / rho[ann]
    tang = flow[..., 0][ann] * tx + flow[..., 1][ann] * ty
    # remove the axle's own translation: tangential component of mean flow averages to ~0 over a ring
    omega = float(np.median(tang / rho[ann]))
    return omega


SHARPNESS_MIN = 60.0   # Laplacian variance below which ground flow is a smear, not a measurement


def _ground_motion(prev_gray, gray, wheel, axle_vel):
    """Ground velocity relative to the axle, px/frame, measured in a patch
    just below the contact point. Returns (velocity, sharpness); velocity
    is None when the ground is too motion-blurred for flow to mean anything
    (a smeared patch returns near-zero flow, which would read as "stopped")."""
    r = wheel["radius_px"]
    bx, by = wheel["cx"], wheel.get("bottom_y", wheel["cy"] + wheel["minor_px"] / 2)
    band = max(6, int(0.35 * r))
    y0, y1 = int(by + 2), int(min(gray.shape[0], by + 2 + band))
    x0, x1 = int(max(0, bx - 0.9 * r)), int(min(gray.shape[1], bx + 0.9 * r))
    if y1 - y0 < 4 or x1 - x0 < 8:
        return None, None
    patch = gray[y0:y1, x0:x1]
    sharp = float(cv2.Laplacian(patch, cv2.CV_64F).var())
    if sharp < SHARPNESS_MIN:
        return None, sharp
    try:
        flow = cv2.calcOpticalFlowFarneback(prev_gray[y0:y1, x0:x1], patch, None,
                                            0.5, 4, max(15, int(r / 2)), 3, 5, 1.2, 0)
    except cv2.error:
        return None, sharp
    vg = np.median(flow.reshape(-1, 2), axis=0)
    return vg - np.array(axle_vel), sharp


def tire_state_for_wheel(prev_gray, gray, wheel, prev_wheel, plane_dir, view, env, fps) -> dict:
    """One wheel, one frame. plane_dir = unit vector of the wheel plane's
    longitudinal direction in the image (axle-to-axle line)."""
    out = {"slip_ratio": None, "slip_angle_deg": None, "camber_deg": None,
           "lateral_drift_r_s": None, "utilisation": None, "state": "unknown",
           "ground_speed_px_s": None, "wheel_speed_px_s": None, "ground_sharpness": None,
           "why": None}
    if wheel is None or prev_wheel is None or prev_gray is None:
        return out
    ratio = wheel["minor_px"] / max(wheel["major_px"], 1e-6)
    if view == "auto":
        view = "side" if ratio >= 0.75 else "compact"
    gamma = (wheel.get("inplane_tilt_deg") or 0.0) if view != "side" else 0.0
    out["camber_deg"] = round(gamma, 1) if wheel.get("inplane_tilt_deg") is not None else None
    oblique = ratio >= 0.45

    axle_vel = (wheel["cx"] - prev_wheel["cx"], wheel["cy"] - prev_wheel["cy"])
    rel, sharp = _ground_motion(prev_gray, gray, wheel, axle_vel)
    out["ground_sharpness"] = round(sharp, 1) if sharp is not None else None
    if rel is None:
        out["why"] = "ground motion-blurred" if sharp is not None else "no ground patch"
        return out
    px, py = plane_dir
    v_long = float(rel[0] * px + rel[1] * py)
    v_lat = float(-rel[0] * py + rel[1] * px)
    v = math.hypot(v_long, v_lat) * fps
    out["ground_speed_px_s"] = round(v, 1)
    if v < env.get("min_ground_speed_px_s", 40.0):
        out["why"] = "ground speed below floor"
        return out
    # sideways step of the contact patch across the ground, in wheel radii per second
    out["lateral_drift_r_s"] = round(v_lat * fps / max(wheel["radius_px"], 1e-6), 3)

    alpha = kappa = None
    if oblique:
        # wheel plane direction is known (axle line): slip angle is meaningful
        alpha = math.degrees(math.atan2(abs(v_lat), abs(v_long) + 1e-6))
        out["slip_angle_deg"] = round(alpha, 1)
        omega = _rim_rotation(prev_gray, gray, wheel)
        if omega is not None:
            w_speed = abs(omega) * wheel["radius_px"] * fps
            out["wheel_speed_px_s"] = round(w_speed, 1)
            g_long = abs(v_long) * fps
            if g_long > 1.0:
                kappa = float(np.clip((w_speed - g_long) / g_long, -1.0, 1.5))
                out["slip_ratio"] = round(kappa, 3)
                # single-frame flow on a small rim is noisy; a near-lock reading
                # from one frame is low confidence until the run-level series confirms it
                out["slip_ratio_confidence"] = "low" if abs(kappa) > 0.6 else "medium"
    else:
        out["why"] = "wheel end-on: rotation and heading not visible; lateral drift only"

    L, T = env["longitudinal"], env["lateral"]
    fx = 0.0 if kappa is None else abs(magic_formula(kappa, L["B"], L["C"], L["D"], L["E"])) / L["D"]
    if alpha is not None:
        fy = abs(magic_formula(math.radians(alpha), T["B"], T["C"], T["D"], T["E"])) / T["D"]
    else:
        # end-on view: map lateral drift onto the lateral curve through an
        # equivalent slip angle, drift of one radius/s ~ the peak angle
        a_eq = math.degrees(math.atan(abs(out["lateral_drift_r_s"]))) * (T["peak_alpha_deg"] / 45.0)
        fy = abs(magic_formula(math.radians(a_eq), T["B"], T["C"], T["D"], T["E"])) / T["D"]
        alpha_eff = a_eq
    alpha_eff = alpha if alpha is not None else alpha_eff
    util = math.sqrt(fx * fx + fy * fy)
    out["utilisation"] = round(util, 3)

    if kappa is not None and kappa <= -0.85:
        out["state"] = "locked"
    elif kappa is not None and kappa >= 0.6:
        out["state"] = "spinning"
    elif alpha_eff > T["peak_alpha_deg"] or (kappa is not None and abs(kappa) > L["peak_kappa"]):
        out["state"] = "sliding"
    elif util >= env.get("limit_fraction", 0.85):
        out["state"] = "limit"
    else:
        out["state"] = "grip"
    return out


# --------------------------------------------------------------- per-run

def self_check(frames: list[dict], env: dict) -> dict:
    """Is the slip estimator trustworthy on this footage?

    Rolling contact is the normal state of a bike, so over a run the median
    |slip ratio| must sit near 0 and the median slip angle well inside the
    grip peak. If they do not, the estimator -- not the tyre -- is off
    (blur, wrong wheel plane, flow aliasing at high ground speed), and the
    per-frame states are recomputed without the offending input rather
    than reported as lock-ups and slides. Mutates frames; returns status."""
    kap, alp = [], []
    for f in frames:
        for side in ("front", "rear"):
            t = (f.get("tire") or {}).get(side) or {}
            if t.get("slip_ratio") is not None: kap.append(abs(t["slip_ratio"]))
            if t.get("slip_angle_deg") is not None: alp.append(t["slip_angle_deg"])
    peak_a = env["lateral"]["peak_alpha_deg"]
    status = {"slip_ratio": "ok", "slip_angle": "ok", "n_kappa": len(kap), "n_alpha": len(alp)}
    if len(kap) < 10:
        status["slip_ratio"] = "too few frames"
    elif float(np.median(kap)) > 0.5:
        status["slip_ratio"] = f"biased on this footage (median |kappa| {np.median(kap):.2f}); dropped from states"
    if len(alp) < 10:
        status["slip_angle"] = "too few frames"
    elif float(np.median(alp)) > 1.5 * peak_a:
        status["slip_angle"] = f"biased on this footage (median alpha {np.median(alp):.0f} deg); dropped from states"
    drop_k = status["slip_ratio"] != "ok"
    drop_a = status["slip_angle"] != "ok"
    if drop_k or drop_a:
        T = env["lateral"]
        for f in frames:
            for side in ("front", "rear"):
                t = (f.get("tire") or {}).get(side)
                if not t or t.get("state") == "unknown":
                    continue
                if drop_k:
                    t["slip_ratio"] = None; t["wheel_speed_px_s"] = None
                if drop_a:
                    t["slip_angle_deg"] = None
                drift = t.get("lateral_drift_r_s")
                if drift is None:
                    t["state"] = "unknown"; t["utilisation"] = None
                    continue
                a_eq = math.degrees(math.atan(abs(drift))) * (T["peak_alpha_deg"] / 45.0)
                fy = abs(magic_formula(math.radians(a_eq), T["B"], T["C"], T["D"], T["E"])) / T["D"]
                t["utilisation"] = round(fy, 3)
                t["state"] = "sliding" if a_eq > T["peak_alpha_deg"] else ("limit" if fy >= env.get("limit_fraction", 0.85) else "grip")
                t["why"] = (t.get("why") or "") + " | states from lateral drift only (estimator self-check)"
    # third check: rolling contact dominates any real run, so if the states
    # now say "sliding" most of the time the lateral-drift channel is biased
    # too (camera pan reads as the tyre stepping sideways) -- unmeasurable
    states = [((f.get("tire") or {}).get(s) or {}).get("state") for f in frames for s in ("front", "rear")]
    known = [s for s in states if s and s != "unknown"]
    share = known.count("sliding") / len(known) if known else 0.0
    status["lateral_drift"] = "ok"
    if known and share > 0.5:
        status["lateral_drift"] = f"biased on this footage (sliding {share:.0%} of frames); states set to unmeasurable"
        for f in frames:
            for s in ("front", "rear"):
                t = (f.get("tire") or {}).get(s)
                if t and t.get("state") != "unknown":
                    t["state"] = "unmeasurable"; t["utilisation"] = None
    status["usable"] = all(status[k] == "ok" for k in ("slip_ratio", "slip_angle", "lateral_drift"))
    status["note"] = ("slip needs a sharp, oblique view of the wheel with sharp ground under it: "
                      "trackside or on-bike footage at higher frame rate, not a blurred chase cam")
    return status


def tire_summary(frames: list[dict], fps: float, env: dict) -> dict:
    out = {"envelope_source": env.get("source"), "estimator_status": self_check(frames, env), "wheels": {}}
    for side in ("front", "rear"):
        recs = [((f.get("tire") or {}).get(side) or {}) for f in frames]
        con = [(((f.get("contact") or {}).get(side) or {}).get("state")) for f in frames]
        kap = np.array([r.get("slip_ratio") if r.get("slip_ratio") is not None else np.nan for r in recs], float)
        alp = np.array([r.get("slip_angle_deg") if r.get("slip_angle_deg") is not None else np.nan for r in recs], float)
        gam = np.array([r.get("camber_deg") if r.get("camber_deg") is not None else np.nan for r in recs], float)
        util = np.array([r.get("utilisation") if r.get("utilisation") is not None else np.nan for r in recs], float)
        states = [r.get("state", "unknown") for r in recs]
        known = [s for s in states if s not in ("unknown", "unmeasurable")]
        # roll of the tyre while slipping: camber during sliding/locked frames
        slip_mask = np.array([s in ("sliding", "locked", "spinning") for s in states])
        roll_when_slipping = gam[slip_mask & ~np.isnan(gam)]
        def st(x):
            v = x[~np.isnan(x)]
            return None if len(v) == 0 else {"mean": round(float(np.mean(np.abs(v))), 3), "p90": round(float(np.percentile(np.abs(v), 90)), 3), "max": round(float(np.max(np.abs(v))), 3), "n": int(len(v))}
        events = _events(frames, side, fps)
        out["wheels"][side] = {
            "slip_ratio": st(kap), "slip_angle_deg": st(alp), "camber_deg": st(gam), "utilisation": st(util),
            "state_share": {s: round(known.count(s) / len(known), 3) for s in ("grip", "limit", "sliding", "locked", "spinning")} if known else None,
            "airborne_share": round(con.count("airborne") / max(1, sum(c is not None and c != "unknown" for c in con)), 3) if any(con) else None,
            "roll_deg_while_slipping": {"mean": round(float(np.mean(np.abs(roll_when_slipping))), 1), "max": round(float(np.max(np.abs(roll_when_slipping))), 1), "n": int(len(roll_when_slipping))} if len(roll_when_slipping) else None,
            "traction_loss_events": events,
        }
    out["note"] = ("slip ratio needs the wheel seen obliquely (rotation visible) and is None in end-on views; "
                   "slip angle and camber are image-plane proxies; utilisation is position on the Magic-Formula "
                   "curve, not a measured force")
    return out


def _events(frames, side, fps, min_s=0.16):
    ev, start, kind = [], None, None
    seq = [((f.get("tire") or {}).get(side) or {}).get("state", "unknown") for f in frames] + ["unknown"]
    for i, s in enumerate(seq):
        active = s in ("sliding", "locked", "spinning")
        if active and start is None:
            start, kind = i, s
        elif (not active or s != kind) and start is not None:
            if (i - start) / fps >= min_s:
                seg = frames[start:i]
                ev.append({"start_s": round(seg[0]["time_s"], 2), "end_s": round(seg[-1]["time_s"], 2), "kind": kind,
                           "peak_slip_angle_deg": max((((f.get("tire") or {}).get(side) or {}).get("slip_angle_deg") or 0) for f in seg),
                           "peak_slip_ratio": max((abs(((f.get("tire") or {}).get(side) or {}).get("slip_ratio") or 0)) for f in seg)})
            start, kind = (i, s) if active else (None, None)
    return ev


# --------------------------------------------------------------- training

def fit_envelope(track_jsons: list[str | Path], crashes: dict[str, list[float]] | None = None,
                 lead_s: float = 3.0, min_frames: int = 200) -> tuple[Path | None, dict]:
    """Learn the grip envelope from the corpus.

    Clean frames (not inside a crash lead-in) from every run give the
    operating band: the 90th percentile of |kappa| and |alpha| is where
    riders in this corpus hold the tyre -- that becomes the limit line.
    Crash lead-in frames give the sliding side: their median |alpha| and
    |kappa|, if above the clean band, become the peak (past it = sliding).
    Refuses with fewer than min_frames scorable frames.
    """
    crashes = crashes or {}
    clean_k, clean_a, pre_k, pre_a = [], [], [], []
    n_frames, skipped = 0, []
    for p in track_jsons:
        p = Path(p)
        if not p.exists():
            continue
        # only runs whose estimator passed its own self-check can teach the envelope
        res = p.parent / "result.json"
        if res.exists():
            st = (json.loads(res.read_text()).get("tire") or {}).get("estimator_status") or {}
            if st and not st.get("usable", False):
                skipped.append(str(p.parent.name)); continue
        d = json.loads(p.read_text())
        cts = crashes.get(p.parent.name) or crashes.get(str(p.parent)) or []
        for f in d["frames"]:
            for side in ("front", "rear"):
                t = (f.get("tire") or {}).get(side) or {}
                a, k = t.get("slip_angle_deg"), t.get("slip_ratio")
                if a is None and k is None:
                    continue
                n_frames += 1
                pre = any(ct - lead_s <= f["time_s"] <= ct for ct in cts)
                (pre_a if pre else clean_a).append(a if a is not None else np.nan)
                (pre_k if pre else clean_k).append(k if k is not None else np.nan)
    report = {"scorable_frames": n_frames, "clean": len(clean_a), "pre_crash": len(pre_a), "runs": len(track_jsons),
              "skipped_biased_runs": skipped}
    if n_frames < min_frames:
        return None, {**report, "fitted": False,
                      "reason": f"need >= {min_frames} scorable wheel-frames from runs whose slip estimator passed its self-check"}
    env = json.loads(json.dumps(DEFAULT_ENVELOPE))
    ca = np.abs(np.array(clean_a, float)); ck = np.abs(np.array(clean_k, float))
    ca, ck = ca[~np.isnan(ca)], ck[~np.isnan(ck)]
    if len(ca):
        env["lateral"]["operating_p90_alpha_deg"] = round(float(np.percentile(ca, 90)), 2)
    if len(ck):
        env["longitudinal"]["operating_p90_kappa"] = round(float(np.percentile(ck, 90)), 3)
    pa = np.abs(np.array(pre_a, float)); pk = np.abs(np.array(pre_k, float))
    pa, pk = pa[~np.isnan(pa)], pk[~np.isnan(pk)]
    if len(pa) >= 20 and len(ca):
        peak = float(np.median(pa))
        if peak > env["lateral"]["operating_p90_alpha_deg"]:
            env["lateral"]["peak_alpha_deg"] = round(peak, 2)
            report["peak_alpha_from_crashes"] = True
    if len(pk) >= 20 and len(ck):
        peak = float(np.median(pk))
        if peak > env["longitudinal"]["operating_p90_kappa"]:
            env["longitudinal"]["peak_kappa"] = round(peak, 3)
            report["peak_kappa_from_crashes"] = True
    # place the Magic-Formula peak at the learned/kept peak: for MF the peak
    # sits near x ~ 1/B * tan(pi/(2C)) -- solve B for the chosen peak
    for axis, key, scale in (("lateral", "peak_alpha_deg", math.pi / 180), ("longitudinal", "peak_kappa", 1.0)):
        C = env[axis]["C"]; xp = env[axis][key] * scale
        if xp > 0:
            env[axis]["B"] = round(math.tan(math.pi / (2 * C)) / xp, 3)
    env["source"] = f"fitted on {len(track_jsons)} runs ({report['clean']} clean, {report['pre_crash']} pre-crash wheel-frames)"
    ver = 1
    latest = _latest_envelope_path()
    if latest:
        ver = int(latest.stem.split("_v")[-1]) + 1
    WEIGHTS_DIR.mkdir(exist_ok=True)
    path = WEIGHTS_DIR / f"tire_model_v{ver:03d}.json"
    env["report"] = report
    path.write_text(json.dumps(env, indent=1))
    return path, {**report, "fitted": True, "envelope": env}
