"""Joint-angle analytics: time series, body-position scoring, rider comparison.

Reads track.json and produces analysis.json with, per joint (ankle, knee,
hip, shoulder, elbow, wrist, neck, torso) plus the gaze sightline:
smoothed time series, range of motion, and time-in-form against coaching
reference envelopes for the DH attack position and the look-ahead vision
cue. riders.yaml maps videos to riders with performance labels so runs can
be compared (good vs poor) and a rider's trend tracked across sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Coaching reference envelopes (degrees) for the neutral/attack position on
# descents, side-view 2D. Wide by design: the rider should live inside them
# and move through them, not sit rigidly at one value.
REFERENCE = {
    "knee_angle":     {"lo": 100, "hi": 155, "cue": "knees bent, ready to absorb"},
    "hip_angle":      {"lo": 55,  "hi": 115, "cue": "hips hinged back and low"},
    "elbow_angle":    {"lo": 90,  "hi": 160, "cue": "elbows bent and wide"},
    "shoulder_angle": {"lo": 20,  "hi": 80,  "cue": "arms forward of torso"},
    "neck_angle":     {"lo": 130, "hi": 180, "cue": "head up, eyes off the front wheel"},
    "torso_angle":    {"lo": 15,  "hi": 55,  "cue": "torso low and level-ish"},
    "ankle_angle":    {"lo": 0,   "hi": 35,  "cue": "heels dropped, shank near vertical"},
    "wrist_angle":    {"lo": -10, "hi": 45,  "cue": "forearms angled down the slope"},
}
# Look-ahead vision cue: sightline between roughly level and moderately
# down-slope. Steeper than hi = staring at the front wheel.
GAZE_REF = {"lo": -10, "hi": 40, "cue": "eyes down the trail, not at the wheel"}

JOINTS = list(REFERENCE)


def _interp_nan(x):
    x = np.array(x, dtype=float)  # copy: never mutate the caller's raw series
    nans = np.isnan(x)
    if nans.all():
        return x
    idx = np.arange(len(x))
    x[nans] = np.interp(idx[nans], idx[~nans], x[~nans])
    return x


def _smooth(x, win):
    win = max(3, int(win) | 1)
    k = np.ones(win) / win
    return np.convolve(np.pad(x, win // 2, mode="edge"), k, mode="valid")[: len(x)]


def analyze(track_json: str | Path, out_json: str | Path | None = None) -> dict:
    data = json.loads(Path(track_json).read_text())
    frames = data["frames"]
    fps = data.get("fps", 30.0) / max(1, data.get("stride", 1))
    times = [round(f["time_s"], 3) for f in frames]
    half_sec = fps / 2

    series, in_form = {}, {}
    for joint, ref in {**REFERENCE, "gaze_angle": GAZE_REF}.items():
        raw = np.array([f.get(joint) if f.get(joint) is not None else np.nan
                        for f in frames])
        coverage = float(np.mean(~np.isnan(raw)))
        if coverage < 0.05:
            continue
        sm = _smooth(_interp_nan(raw), half_sec)
        valid = ~np.isnan(raw)
        ok = (sm >= ref["lo"]) & (sm <= ref["hi"]) & valid
        series[joint] = {
            "values": [round(v, 1) if m else None for v, m in zip(sm, valid)],
            "mean": round(float(np.nanmean(raw)), 1),
            "rom": round(float(np.nanmax(raw) - np.nanmin(raw)), 1),
            "coverage": round(coverage, 2),
            "in_form_pct": round(100 * ok.sum() / max(valid.sum(), 1), 1),
            "ref": ref,
        }
        in_form[joint] = ok

    # attack-position score: per frame, fraction of visible scored joints
    # inside their envelope (gaze excluded; it is its own cue)
    core = [j for j in JOINTS if j in series]
    score = np.zeros(len(frames))
    if core:
        vis = np.zeros(len(frames))
        for j in core:
            v = np.array([frames[i].get(j) is not None for i in range(len(frames))])
            score += in_form[j] & v
            vis += v
        score = np.where(vis > 0, score / np.maximum(vis, 1), np.nan)

    result = {
        "video": data.get("video"),
        "fps": fps,
        "times": times,
        "joints": series,
        "attack_score": [round(s, 2) if not np.isnan(s) else None for s in score],
        "attack_score_mean": round(float(np.nanmean(score)), 3) if core else None,
        "gaze_lookahead_pct": series.get("gaze_angle", {}).get("in_form_pct"),
    }
    if out_json:
        Path(out_json).write_text(json.dumps(result, indent=1))
    return result


def compare(analyses: dict[str, dict]) -> list[dict]:
    """Rank runs for good-vs-poor comparison.

    analyses: label -> analyze() result (label e.g. "rider-A run 2 [good]").
    Returns rows sorted by attack score; the spread between labelled good
    and poor runs shows which cues separate them.
    """
    rows = []
    for label, a in analyses.items():
        row = {"run": label,
               "attack_score": a.get("attack_score_mean"),
               "lookahead_pct": a.get("gaze_lookahead_pct")}
        for j, s in a.get("joints", {}).items():
            row[f"{j}_mean"] = s["mean"]
            row[f"{j}_rom"] = s["rom"]
        rows.append(row)
    return sorted(rows, key=lambda r: -(r["attack_score"] or 0))


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "output/track.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else str(Path(src).parent / "analysis.json")
    r = analyze(src, dst)
    print(f"attack-position score {r['attack_score_mean']}, "
          f"look-ahead {r['gaze_lookahead_pct']}% -> {dst}")
