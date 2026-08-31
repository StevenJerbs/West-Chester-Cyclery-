"""Labeled skeleton + frame overlay -- text labels on joints and boxes,
no filled/highlighted regions (contrast with outline.py's segmentation
fill, and with highlights.py's angle-only HUD).

Draws:
  - a bike bounding box ("frame"), labeled with its detection confidence
  - a rider bounding box computed from the keypoint extent, labeled "rider"
  - thin skeleton lines connecting the raw keypoints
  - each of the seven tracked joints (hip, knee, ankle, shoulder, elbow,
    wrist, neck) labeled by name at its side-averaged position
"""

from __future__ import annotations

from pathlib import Path

import cv2

from track import SKELETON_EDGES, _side_avg

CYAN = (255, 220, 60)
GREEN = (80, 220, 80)
YELLOW = (60, 230, 230)
WHITE = (240, 240, 240)

# joint name -> (left keypoint, right keypoint) for the side-averaged position
JOINT_POINTS = {
    "Hip": ("l_hip", "r_hip"),
    "Knee": ("l_knee", "r_knee"),
    "Ankle": ("l_ankle", "r_ankle"),
    "Shoulder": ("l_shoulder", "r_shoulder"),
    "Elbow": ("l_elbow", "r_elbow"),
    "Wrist": ("l_wrist", "r_wrist"),
}


def _rider_bbox(kps: dict, pad: int = 12):
    if not kps:
        return None
    xs = [p[0] for p in kps.values()]
    ys = [p[1] for p in kps.values()]
    return (int(min(xs) - pad), int(min(ys) - pad),
            int(max(xs) + pad), int(max(ys) + pad))


def annotate_labeled(frame, rec: dict | None):
    if not rec:
        return frame
    kps = rec.get("keypoints", {})

    if rec.get("bike_box"):
        x1, y1, x2, y2 = map(int, rec["bike_box"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), CYAN, 2)
        cv2.putText(frame, f"bike frame  conf {rec.get('bike_conf', 0):.2f}",
                    (x1, max(15, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, CYAN, 2, cv2.LINE_AA)

    box = _rider_bbox(kps)
    if box:
        x1, y1, x2, y2 = box
        cv2.rectangle(frame, (x1, y1), (x2, y2), GREEN, 2)
        cv2.putText(frame, "rider frame", (x1, max(15, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, GREEN, 2, cv2.LINE_AA)

    for a, b in SKELETON_EDGES:
        if a in kps and b in kps:
            pa, pb = kps[a], kps[b]
            cv2.line(frame, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])),
                     GREEN, 1, cv2.LINE_AA)
    for p in kps.values():
        cv2.circle(frame, (int(p[0]), int(p[1])), 3, WHITE, -1, cv2.LINE_AA)

    for name, (l, r) in JOINT_POINTS.items():
        pt = _side_avg(kps, l, r)
        if pt:
            x, y = int(pt[0]), int(pt[1])
            cv2.circle(frame, (x, y), 4, YELLOW, -1, cv2.LINE_AA)
            cv2.putText(frame, name, (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, YELLOW, 1, cv2.LINE_AA)
    return frame


def render_labeled_video(video_path: str | Path, out_path: str | Path,
                         track_json: dict, rotate_deg: int = 0) -> Path:
    from track import _ROTATIONS

    rot_code = _ROTATIONS.get(rotate_deg % 360)
    frames_by_idx = {f["frame"]: f for f in track_json["frames"]}

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    writer = None
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if rot_code is not None:
            frame = cv2.rotate(frame, rot_code)
        annotate_labeled(frame, frames_by_idx.get(i))
        if writer is None:
            h, w = frame.shape[:2]
            writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                                     fps, (w, h))
        writer.write(frame)
        i += 1
    if writer:
        writer.release()
    cap.release()
    return Path(out_path)
