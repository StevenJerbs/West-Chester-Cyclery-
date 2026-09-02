"""Learned control/crash-risk model: crash footage as negatives.

Where crash videos plug in: NOT the pose/detection fine-tune (that layer
learns where joints are, which is label-agnostic to crashing -- crash
frames actually help it as unusual-pose training data). The supervised
signal a crash carries is about the *kinematic time series*: in the
seconds before a rider goes down, joint dynamics and bike motion look
measurably different from riding in control. So this module trains a
classifier over windowed kinematic features:

  positive (label 1, "in control")  -- windows from clean runs
  negative (label 0, "pre-crash")   -- windows whose end falls inside the
                                       lead-in to a labeled crash moment

Crash moments are labeled per video in data/crashes.yaml:

    crashes:
      - video: <track.json's video id / stem>
        crash_times_s: [12.4, 31.0]   # moment the rider goes down
        # windows ending within `lead_s` before each crash time become
        # negatives; windows overlapping the crash itself are dropped
        # (mid-crash pose data is unreliable), as are windows within
        # `guard_s` after (remounting, walking).

The classifier is deliberately small (standardized logistic regression):
with tens-of-windows datasets anything bigger memorizes. Report
leave-one-video-out AUC, not train accuracy. Models are versioned
alongside the pose checkpoints as weights/control_model_vNNN.joblib.

Output: control_score(track_json) -> (times, probability-in-control),
same shape as suspension.suspension_score, so overlays and dashboard
panels can consume it identically.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = ROOT / "weights"

ANGLE_KEYS = ["knee_angle", "hip_angle", "elbow_angle", "shoulder_angle",
              "neck_angle", "torso_angle", "ankle_angle", "wrist_angle",
              "gaze_angle"]
MOTION_KEYS = ["bike_center_y", "bike_height", "com_offset_x"]

WINDOW_S = 2.0
HOP_S = 0.5


def _interp_nan(x):
    x = np.array(x, dtype=float)  # copy: never mutate the caller's raw series
    nans = np.isnan(x)
    if nans.all() or len(x) == 0:
        return np.zeros_like(x)
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def feature_names() -> list[str]:
    names = []
    for k in ANGLE_KEYS + MOTION_KEYS:
        names += [f"{k}_mean", f"{k}_std", f"{k}_absvel"]
    names += ["pose_coverage", "bike_coverage"]
    return names


def extract_windows(track_json: str | Path | dict,
                    window_s: float = WINDOW_S, hop_s: float = HOP_S):
    """Slide a window over one run's tracking record.

    Returns (window_end_times, feature_matrix). Features per series:
    mean, std, mean |velocity|; plus pose/bike detection coverage.
    Windows with under 30% pose coverage are dropped -- there is no
    kinematic signal to classify in them.
    """
    data = (track_json if isinstance(track_json, dict)
            else json.loads(Path(track_json).read_text()))
    frames = data["frames"]
    fps = data.get("fps", 30.0) / max(1, data.get("stride", 1))
    if not frames:
        return np.array([]), np.zeros((0, len(feature_names())))

    series = {}
    for k in ANGLE_KEYS + MOTION_KEYS:
        raw = np.array([f.get(k) if f.get(k) is not None else np.nan
                        for f in frames], dtype=float)
        series[k] = (raw, _interp_nan(raw))
    pose_ok = np.array([len(f.get("keypoints", {})) >= 6 for f in frames], float)
    bike_ok = np.array([f.get("bike_box") is not None for f in frames], float)
    times = np.array([f["time_s"] for f in frames])

    win = max(3, int(window_s * fps))
    hop = max(1, int(hop_s * fps))

    rows, ends = [], []
    for start in range(0, len(frames) - win + 1, hop):
        sl = slice(start, start + win)
        if pose_ok[sl].mean() < 0.3:
            continue
        feats = []
        for k in ANGLE_KEYS + MOTION_KEYS:
            raw, filled = series[k]
            seg_raw, seg = raw[sl], filled[sl]
            valid = ~np.isnan(seg_raw)
            if valid.mean() < 0.2:
                feats += [0.0, 0.0, 0.0]
                continue
            vel = np.abs(np.gradient(seg)) * fps
            feats += [float(np.nanmean(seg_raw)), float(np.nanstd(seg_raw)),
                      float(vel.mean())]
        feats += [float(pose_ok[sl].mean()), float(bike_ok[sl].mean())]
        rows.append(feats)
        ends.append(float(times[start + win - 1]))
    return np.array(ends), np.array(rows)


def label_windows(end_times: np.ndarray, crash_times: list[float],
                  lead_s: float = 4.0, guard_s: float = 6.0):
    """Label windows for one video. Returns (labels, keep_mask).

    label 0: window ends inside the lead-in [crash - lead_s, crash].
    dropped: window ends inside (crash, crash + guard_s] -- mid-crash and
             aftermath frames carry no in-control signal either way.
    label 1: everything else (clean riding).
    A video with no crash_times is all label 1.
    """
    labels = np.ones(len(end_times), dtype=int)
    keep = np.ones(len(end_times), dtype=bool)
    for ct in crash_times or []:
        pre = (end_times >= ct - lead_s) & (end_times <= ct)
        post = (end_times > ct) & (end_times <= ct + guard_s)
        labels[pre] = 0
        keep &= ~post
    return labels, keep


def _latest_model_path() -> Path | None:
    if WEIGHTS_DIR.exists():
        models = sorted(WEIGHTS_DIR.glob("control_model_v*.joblib"))
        if models:
            return models[-1]
    return None


def train(datasets: list[dict], min_negatives: int = 8):
    """Train the control classifier and save the next version.

    datasets: [{"track_json": path, "crash_times_s": [..]}] -- include the
    clean runs too; they supply the positives.
    Refuses to train with fewer than min_negatives pre-crash windows:
    below that the leave-one-video-out estimate is meaningless and the
    saved model would be noise.
    Returns (model_path, report dict).
    """
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    X, y, groups = [], [], []
    for gi, d in enumerate(datasets):
        ends, feats = extract_windows(d["track_json"])
        if len(ends) == 0:
            continue
        labels, keep = label_windows(ends, d.get("crash_times_s", []))
        X.append(feats[keep]); y.append(labels[keep])
        groups += [gi] * int(keep.sum())
    X = np.vstack(X); y = np.concatenate(y); groups = np.array(groups)

    n_neg = int((y == 0).sum())
    report = {"windows": len(y), "positives": int((y == 1).sum()),
              "negatives": n_neg, "videos": len(datasets)}
    if n_neg < min_negatives:
        raise ValueError(
            f"only {n_neg} pre-crash windows across the labeled videos; "
            f"need at least {min_negatives}. Add more crash footage (each "
            f"distinct crash with ~5s of riding before it yields ~"
            f"{int(4.0/HOP_S)} negatives).")

    def new_model():
        return make_pipeline(StandardScaler(),
                             LogisticRegression(max_iter=2000, C=0.5,
                                                class_weight="balanced"))

    # leave-one-video-out: the honest estimate at this data scale
    aucs = []
    for g in np.unique(groups):
        tr, te = groups != g, groups == g
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        m = new_model().fit(X[tr], y[tr])
        aucs.append(roc_auc_score(y[te], m.predict_proba(X[te])[:, 1]))
    report["loo_auc"] = round(float(np.mean(aucs)), 3) if aucs else None

    model = new_model().fit(X, y)
    version = 1
    latest = _latest_model_path()
    if latest:
        version = int(latest.stem.split("_v")[-1]) + 1
    WEIGHTS_DIR.mkdir(exist_ok=True)
    path = WEIGHTS_DIR / f"control_model_v{version:03d}.joblib"
    joblib.dump({"model": model, "features": feature_names(),
                 "window_s": WINDOW_S, "hop_s": HOP_S, "report": report}, path)
    return path, report


def control_score(track_json: str | Path | dict, model_path: str | Path | None = None):
    """(times, P(in control)) for one run, from the latest trained model."""
    import joblib

    path = Path(model_path) if model_path else _latest_model_path()
    if path is None:
        raise FileNotFoundError("no trained control model in weights/ yet")
    bundle = joblib.load(path)
    ends, feats = extract_windows(track_json,
                                  bundle["window_s"], bundle["hop_s"])
    if len(ends) == 0:
        return ends, np.array([])
    return ends, bundle["model"].predict_proba(feats)[:, 1]
