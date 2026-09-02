"""Per-discipline form envelopes -- hand-set coaching ranges, replaced by
learned ranges from advanced riders as labeled footage accumulates.

Two layers:
  COACHING   -- broad ranges from coaching convention, per discipline.
                These are the fallback and the cold-start prior.
  learned    -- for any discipline with >= MIN_ADVANCED_RUNS runs tagged
                level: advanced in data/riders.yaml, the 10th-90th
                percentile of each joint's smoothed angle across those
                runs. Grading uses the learned band where it exists and
                says so in the output (`source: learned` vs `coaching`),
                so a grade never silently rests on a hand-set number
                once real advanced data is available.

"Advanced" here means the level recorded in riders.yaml by the person
labeling the run (race result, coach's assessment, self-report) -- the
model does not infer it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MIN_ADVANCED_RUNS = 3

DISCIPLINES = ["downhill", "enduro", "trail", "xc", "dirt_jump", "trials",
               "bmx_race", "bmx_park", "road", "gravel", "cyclocross", "track"]

_DH = {
    "knee_angle":     {"lo": 100, "hi": 155, "cue": "knees bent, ready to absorb"},
    "hip_angle":      {"lo": 55,  "hi": 115, "cue": "hips hinged back and low"},
    "elbow_angle":    {"lo": 90,  "hi": 160, "cue": "elbows bent and wide"},
    "shoulder_angle": {"lo": 20,  "hi": 80,  "cue": "arms forward of torso"},
    "neck_angle":     {"lo": 130, "hi": 180, "cue": "head up, eyes off the front wheel"},
    "torso_angle":    {"lo": 15,  "hi": 55,  "cue": "torso low and level-ish"},
    "ankle_angle":    {"lo": 0,   "hi": 35,  "cue": "heels dropped, shank near vertical"},
    "wrist_angle":    {"lo": -10, "hi": 45,  "cue": "forearms angled down the slope"},
    "gaze_angle":     {"lo": -10, "hi": 40,  "cue": "eyes down the trail, not at the wheel"},
}
_XC = {  # seated/standing pedaling: more extended, higher torso
    "knee_angle":     {"lo": 70,  "hi": 175, "cue": "full pedal stroke range"},
    "hip_angle":      {"lo": 40,  "hi": 110, "cue": "hinged, not slumped"},
    "elbow_angle":    {"lo": 120, "hi": 175, "cue": "soft elbows, not locked"},
    "shoulder_angle": {"lo": 30,  "hi": 90,  "cue": "arms relaxed forward"},
    "neck_angle":     {"lo": 135, "hi": 180, "cue": "head up on descents"},
    "torso_angle":    {"lo": 25,  "hi": 60,  "cue": "torso angle steady"},
    "ankle_angle":    {"lo": 0,   "hi": 45,  "cue": "stable ankle through the stroke"},
    "wrist_angle":    {"lo": -15, "hi": 40,  "cue": "neutral wrists"},
    "gaze_angle":     {"lo": -10, "hi": 35,  "cue": "look ahead, scan the line"},
}
_ROAD = {
    "knee_angle":     {"lo": 65,  "hi": 150, "cue": "knee extension short of lockout"},
    "hip_angle":      {"lo": 35,  "hi": 95,  "cue": "closed hip in the drops, open on the hoods"},
    "elbow_angle":    {"lo": 110, "hi": 170, "cue": "bent elbows absorb road buzz"},
    "shoulder_angle": {"lo": 40,  "hi": 100, "cue": "relaxed shoulders"},
    "neck_angle":     {"lo": 130, "hi": 180, "cue": "head up, not craned"},
    "torso_angle":    {"lo": 20,  "hi": 50,  "cue": "flat, stable back"},
    "ankle_angle":    {"lo": 0,   "hi": 40,  "cue": "consistent ankling"},
    "wrist_angle":    {"lo": -20, "hi": 30,  "cue": "neutral wrists on the bars"},
    "gaze_angle":     {"lo": -15, "hi": 30,  "cue": "eyes up the road"},
}
_JUMP = {  # dirt jump / BMX park / trials: extreme ranges are normal
    "knee_angle":     {"lo": 60,  "hi": 170, "cue": "deep compress, full extension"},
    "hip_angle":      {"lo": 40,  "hi": 140, "cue": "big hinge on take-off and landing"},
    "elbow_angle":    {"lo": 60,  "hi": 170, "cue": "arms absorb and extend"},
    "shoulder_angle": {"lo": 10,  "hi": 110, "cue": "shoulders drive the bike"},
    "neck_angle":     {"lo": 120, "hi": 180, "cue": "spot the landing"},
    "torso_angle":    {"lo": 10,  "hi": 80,  "cue": "torso follows the arc"},
    "ankle_angle":    {"lo": 0,   "hi": 50,  "cue": "feet planted"},
    "wrist_angle":    {"lo": -30, "hi": 60,  "cue": "wrists load and release"},
    "gaze_angle":     {"lo": -20, "hi": 50,  "cue": "eyes on the landing"},
}

COACHING = {
    "downhill": _DH, "enduro": _DH, "trail": _DH,
    "xc": _XC, "cyclocross": _XC, "gravel": _XC,
    "road": _ROAD, "track": _ROAD,
    "dirt_jump": _JUMP, "bmx_park": _JUMP, "trials": _JUMP, "bmx_race": _JUMP,
}


def _advanced_runs(discipline: str) -> list[Path]:
    """analysis.json paths for runs tagged level: advanced in riders.yaml."""
    import yaml
    reg = ROOT / "data" / "riders.yaml"
    if not reg.exists():
        return []
    riders = yaml.safe_load(reg.read_text()).get("riders", []) or []
    paths = []
    for r in riders:
        if str(r.get("level", "")).lower() not in ("advanced", "pro", "elite"):
            continue
        for run in r.get("runs", []):
            if run.get("discipline", "").lower() != discipline:
                continue
            vid = run.get("clip") or run.get("video")
            if not vid:
                continue
            for cand in (ROOT / "output" / str(vid).split(" ")[0] / "analysis.json",
                         ROOT / "output" / "candidates" / str(vid).split(" ")[0] / "analysis.json"):
                if cand.exists():
                    paths.append(cand)
                    break
    return paths


def learned_envelope(discipline: str) -> dict | None:
    paths = _advanced_runs(discipline)
    if len(paths) < MIN_ADVANCED_RUNS:
        return None
    per_joint: dict[str, list[float]] = {}
    for p in paths:
        a = json.loads(p.read_text())
        for j, s in a.get("joints", {}).items():
            per_joint.setdefault(j, []).extend(v for v in s["values"] if v is not None)
    env = {}
    for j, vals in per_joint.items():
        if len(vals) < 50:
            continue
        lo, hi = np.percentile(vals, [10, 90])
        cue = COACHING["downhill"].get(j, {}).get("cue", "")
        env[j] = {"lo": round(float(lo), 1), "hi": round(float(hi), 1), "cue": cue}
    return env or None


def envelope_for(discipline: str) -> tuple[dict, str]:
    """(envelope, source) with source 'learned' or 'coaching'."""
    d = (discipline or "downhill").lower()
    if d not in COACHING:
        d = "downhill"
    learned = learned_envelope(d)
    if learned:
        merged = dict(COACHING[d])
        merged.update(learned)
        return merged, "learned"
    return COACHING[d], "coaching"
