"""Form grading: score a run against its discipline's envelope, highlight
where and when form falls outside the advanced band, estimate fatigue
drift, attach crash risk, and (when enough labeled runs exist) report
which factors separate advanced riders from the rest.

Outputs are designed to be read by a human coach and by an agent:
  grade            -- 0-100, weighted share of time inside the envelope
  per_joint        -- in-form %, mean, ROM, worst deviation, and the
                      envelope + its source (learned vs coaching)
  deviations       -- timestamped windows where a joint sat outside its
                      band for >= MIN_DEV_S, with severity in degrees --
                      these are the "not on par" highlights the labeled
                      video draws
  fatigue          -- first-half vs second-half drift of grade, ROM and
                      look-ahead; a negative drift is the fatigue signal
  crash_risk       -- from crash_model if a trained control model exists
  cornering        -- from cornering.analyze_cornering
  factor_report    -- coefficient ranking from the control model and, when
                      >= MIN_LEVEL_RUNS runs per level are labeled, a
                      per-metric advanced-vs-other spread. Absent when the
                      data can't support it -- reported as such rather
                      than invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from disciplines import envelope_for

ROOT = Path(__file__).resolve().parents[1]
MIN_DEV_S = 0.5
MIN_LEVEL_RUNS = 3

JOINT_WEIGHTS = {  # what a coach looks at first
    "knee_angle": 1.5, "hip_angle": 1.5, "elbow_angle": 1.2, "neck_angle": 1.0,
    "gaze_angle": 1.2, "torso_angle": 1.0, "shoulder_angle": 0.8,
    "ankle_angle": 0.6, "wrist_angle": 0.5,
}


def _deviation_windows(times, values, lo, hi, min_s):
    out, start, worst = [], None, 0.0
    vals = list(values) + [None]
    for i, v in enumerate(vals):
        outside = v is not None and (v < lo or v > hi)
        if outside:
            if start is None:
                start, worst = i, 0.0
            worst = max(worst, (lo - v) if v < lo else (v - hi))
        elif start is not None:
            if times[i - 1] - times[start] >= min_s:
                out.append({"start_s": round(float(times[start]), 2), "end_s": round(float(times[i - 1]), 2),
                            "severity_deg": round(float(worst), 1),
                            "side": "below" if values[start] is not None and values[start] < lo else "above"})
            start = None
    return out


def grade_run(analysis: dict, discipline: str) -> dict:
    env, source = envelope_for(discipline)
    times = np.array(analysis["times"])
    per_joint, deviations = {}, []
    num = den = 0.0
    for joint, ref in env.items():
        s = analysis.get("joints", {}).get(joint)
        if not s:
            continue
        vals = s["values"]
        valid = [v for v in vals if v is not None]
        if not valid:
            continue
        inside = sum(1 for v in valid if ref["lo"] <= v <= ref["hi"]) / len(valid)
        w = JOINT_WEIGHTS.get(joint, 1.0)
        num += w * inside; den += w
        devs = _deviation_windows(times, vals, ref["lo"], ref["hi"], MIN_DEV_S)
        for d in devs:
            d["joint"] = joint; d["cue"] = ref.get("cue", "")
        deviations += devs
        per_joint[joint] = {
            "in_form_pct": round(100 * inside, 1), "mean": s["mean"], "rom": s["rom"],
            "band": {"lo": ref["lo"], "hi": ref["hi"], "source": source},
            "cue": ref.get("cue", ""),
            "worst_deviation_deg": max((d["severity_deg"] for d in devs), default=0.0),
        }
    grade = round(100 * num / den, 1) if den else None
    deviations.sort(key=lambda d: -d["severity_deg"])
    return {"grade": grade, "envelope_source": source, "discipline": discipline,
            "per_joint": per_joint, "deviations": deviations}


def fatigue_index(analysis: dict) -> dict:
    """First-half vs second-half drift. Negative = form degrading."""
    att = np.array([a if a is not None else np.nan for a in analysis["attack_score"]], dtype=float)
    n = len(att)
    if n < 20:
        return {"available": False, "reason": "run too short"}
    h = n // 2
    def mean(x):
        x = x[np.isfinite(x)]
        return float(x.mean()) if len(x) else np.nan
    att_drift = mean(att[h:]) - mean(att[:h])
    gaze = analysis["joints"].get("gaze_angle", {}).get("values")
    gz = np.array([v if v is not None else np.nan for v in gaze], dtype=float) if gaze else None
    gaze_drift = (mean(gz[h:]) - mean(gz[:h])) if gz is not None else np.nan
    knee = analysis["joints"].get("knee_angle", {}).get("values")
    kn = np.array([v if v is not None else np.nan for v in knee], dtype=float) if knee else None
    rom_drift = ((np.nanmax(kn[h:]) - np.nanmin(kn[h:])) - (np.nanmax(kn[:h]) - np.nanmin(kn[:h]))) if kn is not None and np.isfinite(kn).sum() > 4 else np.nan
    flags = []
    if np.isfinite(att_drift) and att_drift < -0.1:
        flags.append("attack-position time fell in the second half")
    if np.isfinite(gaze_drift) and gaze_drift > 8:
        flags.append("sightline dropped toward the wheel later in the run")
    if np.isfinite(rom_drift) and rom_drift < -15:
        flags.append("knee range of motion shrank later in the run (stiffening)")
    return {"available": True,
            "attack_drift": round(att_drift, 3) if np.isfinite(att_drift) else None,
            "gaze_drift_deg": round(gaze_drift, 1) if np.isfinite(gaze_drift) else None,
            "knee_rom_drift_deg": round(float(rom_drift), 1) if np.isfinite(rom_drift) else None,
            "flags": flags,
            "note": "heuristic drift over one run; a learned fatigue model needs runs labeled with rider-reported fatigue or lap times"}


def crash_risk(track_json_path) -> dict:
    try:
        from crash_model import control_score, _latest_model_path
        if _latest_model_path() is None:
            return {"available": False, "reason": "no trained control model yet (needs crash-labeled footage)"}
        times, p = control_score(track_json_path)
        if len(p) == 0:
            return {"available": False, "reason": "no scorable windows"}
        risk = 1 - p
        worst = int(np.argmax(risk))
        return {"available": True, "mean_risk": round(float(risk.mean()), 3),
                "peak_risk": round(float(risk[worst]), 3), "peak_at_s": round(float(times[worst]), 2),
                "series": [[round(float(t), 2), round(float(r), 3)] for t, r in zip(times, risk)]}
    except Exception as e:  # never let an optional layer sink the run
        return {"available": False, "reason": str(e)}


def factor_report() -> dict:
    """What separates advanced riders -- only when the data can say so."""
    import yaml
    out = {"available": False}
    try:
        from crash_model import _latest_model_path, feature_names
        import joblib
        mp = _latest_model_path()
        if mp:
            bundle = joblib.load(mp)
            lr = bundle["model"].named_steps["logisticregression"]
            coef = lr.coef_[0]
            names = bundle["features"]
            order = np.argsort(-np.abs(coef))[:10]
            out["crash_risk_factors"] = [
                {"feature": names[i], "weight": round(float(coef[i]), 3),
                 "direction": "protective" if coef[i] > 0 else "risk"} for i in order]
            out["crash_model_report"] = bundle.get("report")
            out["available"] = True
    except Exception as e:
        out["crash_risk_factors_error"] = str(e)

    reg = ROOT / "data" / "riders.yaml"
    if reg.exists():
        riders = yaml.safe_load(reg.read_text()).get("riders", []) or []
        by_level: dict[str, list[dict]] = {}
        for r in riders:
            lvl = "advanced" if str(r.get("level", "")).lower() in ("advanced", "pro", "elite") else "other"
            for run in r.get("runs", []):
                vid = str(run.get("clip") or run.get("video") or "").split(" ")[0]
                for cand in (ROOT / "output" / vid / "analysis.json",
                             ROOT / "output" / "candidates" / vid / "analysis.json"):
                    if cand.exists():
                        by_level.setdefault(lvl, []).append(json.loads(cand.read_text()))
                        break
        n_adv, n_oth = len(by_level.get("advanced", [])), len(by_level.get("other", []))
        out["labeled_runs"] = {"advanced": n_adv, "other": n_oth}
        if n_adv >= MIN_LEVEL_RUNS and n_oth >= MIN_LEVEL_RUNS:
            spread = {}
            for key in ("attack_score_mean", "gaze_lookahead_pct"):
                a = [x.get(key) for x in by_level["advanced"] if x.get(key) is not None]
                o = [x.get(key) for x in by_level["other"] if x.get(key) is not None]
                if a and o:
                    spread[key] = {"advanced_mean": round(float(np.mean(a)), 3),
                                   "other_mean": round(float(np.mean(o)), 3)}
            out["advanced_vs_other"] = spread
            out["available"] = True
        else:
            out["advanced_vs_other"] = None
            out["note"] = (f"need >= {MIN_LEVEL_RUNS} runs labeled advanced and >= {MIN_LEVEL_RUNS} "
                           f"labeled otherwise to report what separates them; have {n_adv}/{n_oth}")
    return out
