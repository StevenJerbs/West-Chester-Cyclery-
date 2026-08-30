"""Bike + rider tracking for the downhill kinematic visual model.

Runs two YOLOv8 models per frame:
  - yolov8n.pt        -> bicycle bounding box (COCO class 1)
  - yolov8n-pose.pt   -> rider keypoints (COCO 17-keypoint skeleton)

From those it derives per-frame kinematic geometry: bike pitch, wheelbase
proxy, rider hip/knee/elbow angles, and rider center-of-mass position
relative to the bike. Results are returned as a list of FrameTrack records
and can be dumped to JSON for the suspension scorer and highlight picker.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import numpy as np

BICYCLE_CLASS = 1  # COCO class id

# COCO keypoint indices used for rider geometry
KP = {
    "nose": 0,
    "l_shoulder": 5, "r_shoulder": 6,
    "l_elbow": 7, "r_elbow": 8,
    "l_wrist": 9, "r_wrist": 10,
    "l_hip": 11, "r_hip": 12,
    "l_knee": 13, "r_knee": 14,
    "l_ankle": 15, "r_ankle": 16,
}

SKELETON_EDGES = [
    ("l_shoulder", "r_shoulder"), ("l_hip", "r_hip"),
    ("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"),
    ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist"),
    ("l_shoulder", "l_hip"), ("r_shoulder", "r_hip"),
    ("l_hip", "l_knee"), ("l_knee", "l_ankle"),
    ("r_hip", "r_knee"), ("r_knee", "r_ankle"),
]


@dataclass
class FrameTrack:
    frame: int
    time_s: float
    bike_box: list | None = None          # [x1, y1, x2, y2]
    bike_conf: float = 0.0
    bike_center_y: float | None = None    # vertical center, px
    bike_height: float | None = None      # box height, px (suspension proxy)
    keypoints: dict = field(default_factory=dict)  # name -> [x, y, conf]
    hip_angle: float | None = None        # shoulder-hip-knee, degrees
    knee_angle: float | None = None       # hip-knee-ankle, degrees
    elbow_angle: float | None = None      # shoulder-elbow-wrist, degrees
    com_offset_x: float | None = None     # rider COM x minus bike center x, px


def _angle(a, b, c) -> float | None:
    """Angle at vertex b (degrees) for points a-b-c, or None if degenerate."""
    v1 = np.array(a[:2]) - np.array(b[:2])
    v2 = np.array(c[:2]) - np.array(b[:2])
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cosang = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return math.degrees(math.acos(cosang))


def _side_avg(kps: dict, left: str, right: str):
    """Average of the left/right keypoint pair, using whichever is confident."""
    pts = [kps[k] for k in (left, right) if k in kps and kps[k][2] > 0.3]
    if not pts:
        return None
    return np.mean([p[:2] for p in pts], axis=0).tolist()


class BikeRiderTracker:
    def __init__(self, det_weights: str = "yolov8n.pt",
                 pose_weights: str = "yolov8n-pose.pt", conf: float = 0.25):
        from ultralytics import YOLO  # imported lazily; heavy dependency
        self.det = YOLO(det_weights)
        self.pose = YOLO(pose_weights)
        self.conf = conf

    def track_frame(self, frame_bgr, idx: int, time_s: float) -> FrameTrack:
        rec = FrameTrack(frame=idx, time_s=time_s)

        det = self.det(frame_bgr, conf=self.conf, verbose=False)[0]
        best = None
        for box in det.boxes:
            if int(box.cls) == BICYCLE_CLASS:
                c = float(box.conf)
                if best is None or c > best[1]:
                    best = (box.xyxy[0].tolist(), c)
        if best:
            (x1, y1, x2, y2), rec.bike_conf = best
            rec.bike_box = [x1, y1, x2, y2]
            rec.bike_center_y = (y1 + y2) / 2
            rec.bike_height = y2 - y1

        pose = self.pose(frame_bgr, conf=self.conf, verbose=False)[0]
        if pose.keypoints is not None and len(pose.keypoints) > 0:
            person = self._closest_person(pose, rec.bike_box)
            if person is not None:
                for name, i in KP.items():
                    x, y, c = person[i]
                    if c > 0.3:
                        rec.keypoints[name] = [float(x), float(y), float(c)]
                self._derive_geometry(rec)
        return rec

    def _closest_person(self, pose_result, bike_box):
        """Pick the detected person whose hips sit closest to the bike box."""
        kps = pose_result.keypoints.data.cpu().numpy()  # (n, 17, 3)
        if bike_box is None:
            return kps[0]
        bx = (bike_box[0] + bike_box[2]) / 2
        by = (bike_box[1] + bike_box[3]) / 2
        best, best_d = None, float("inf")
        for person in kps:
            hips = [person[i] for i in (KP["l_hip"], KP["r_hip"]) if person[i][2] > 0.3]
            if not hips:
                continue
            hx, hy = np.mean([h[:2] for h in hips], axis=0)
            d = math.hypot(hx - bx, hy - by)
            if d < best_d:
                best, best_d = person, d
        return best if best is not None else kps[0]

    def _derive_geometry(self, rec: FrameTrack):
        k = rec.keypoints
        shoulder = _side_avg(k, "l_shoulder", "r_shoulder")
        hip = _side_avg(k, "l_hip", "r_hip")
        knee = _side_avg(k, "l_knee", "r_knee")
        ankle = _side_avg(k, "l_ankle", "r_ankle")
        elbow = _side_avg(k, "l_elbow", "r_elbow")
        wrist = _side_avg(k, "l_wrist", "r_wrist")

        if shoulder and hip and knee:
            rec.hip_angle = _angle(shoulder, hip, knee)
        if hip and knee and ankle:
            rec.knee_angle = _angle(hip, knee, ankle)
        if shoulder and elbow and wrist:
            rec.elbow_angle = _angle(shoulder, elbow, wrist)
        if hip and shoulder and rec.bike_box:
            com_x = (hip[0] + shoulder[0]) / 2
            bike_cx = (rec.bike_box[0] + rec.bike_box[2]) / 2
            rec.com_offset_x = com_x - bike_cx


def track_video(video_path: str | Path, out_json: str | Path,
                stride: int = 1, max_frames: int | None = None) -> list[FrameTrack]:
    """Track every `stride`-th frame of a video; write records to JSON."""
    tracker = BikeRiderTracker()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    records, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % stride == 0:
            records.append(tracker.track_frame(frame, idx, idx / fps))
        idx += 1
        if max_frames and idx >= max_frames:
            break
    cap.release()

    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(
        {"video": str(video_path), "fps": fps, "stride": stride,
         "frames": [asdict(r) for r in records]}, indent=1))
    return records
