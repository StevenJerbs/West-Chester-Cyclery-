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
    "l_eye": 1, "r_eye": 2,
    "l_ear": 3, "r_ear": 4,
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
    shoulder_angle: float | None = None   # elbow-shoulder-hip, degrees
    neck_angle: float | None = None       # nose-shoulder-hip, degrees
    wrist_angle: float | None = None      # forearm inclination vs horizontal (no hand kp)
    ankle_angle: float | None = None      # shank inclination vs vertical (no toe kp)
    torso_angle: float | None = None      # hip->shoulder line vs horizontal, degrees
    gaze_angle: float | None = None       # ear->nose sightline vs horizontal; + = down
    gaze_origin: list | None = None       # [x, y] head point the sightline starts from
    gaze_vec: list | None = None          # unit [dx, dy] of the sightline
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
    # Inference sizes. YOLO's default 640 turns a distant bike in a 1920-px
    # FPV/chase frame into a ~40 px object and can lose it; 1280 keeps it
    # but misses some frames 640 catches, so 1280 is the retry, not the default.
    IMGSZ = 640
    IMGSZ_RETRY = 1280

    def __init__(self, det_weights: str = "yolov8n.pt",
                 pose_weights: str = "yolov8n-pose.pt", conf: float = 0.25):
        from ultralytics import YOLO  # imported lazily; heavy dependency
        self.det = YOLO(det_weights)
        self.pose = YOLO(pose_weights)
        self.conf = conf
        self._last_hip = None   # rider identity continuity across frames
        self._miss = 0          # frames since the rider was last confirmed
        self._last_box = None   # last bike box, for the zoomed retry
        self._box_miss = 0

    def _best_bike(self, det, offset=(0, 0), scale=1.0):
        best = None
        for box in det.boxes:
            if int(box.cls) == BICYCLE_CLASS:
                c = float(box.conf)
                if best is None or c > best[1]:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    best = ([x1 / scale + offset[0], y1 / scale + offset[1],
                             x2 / scale + offset[0], y2 / scale + offset[1]], c)
        return best

    def _roi_detect(self, frame_bgr, center, size):
        """Zoomed retry for a small, distant bike: crop a square around the
        rider (or the last bike box), upscale it so the bike is a few hundred
        px, and run the detector on that. Coordinates are mapped back."""
        h, w = frame_bgr.shape[:2]
        size = int(max(224, min(size, min(h, w))))
        cx, cy = center
        x0, y0 = int(np.clip(cx - size / 2, 0, w - size)), int(np.clip(cy - size / 2, 0, h - size))
        crop = frame_bgr[y0:y0 + size, x0:x0 + size]
        scale = 640.0 / size
        if scale > 1.0:
            crop = cv2.resize(crop, (640, 640), interpolation=cv2.INTER_CUBIC)
        else:
            scale = 1.0
        det = self.det(crop, conf=max(0.15, self.conf - 0.1), imgsz=640, verbose=False)[0]
        return self._best_bike(det, offset=(x0, y0), scale=scale)

    def track_frame(self, frame_bgr, idx: int, time_s: float) -> FrameTrack:
        rec = FrameTrack(frame=idx, time_s=time_s)

        best = None
        for imgsz in (self.IMGSZ, self.IMGSZ_RETRY):
            det = self.det(frame_bgr, conf=self.conf, imgsz=imgsz, verbose=False)[0]
            best = self._best_bike(det)
            if best:
                break

        pose = self.pose(frame_bgr, conf=self.conf, imgsz=self.IMGSZ, verbose=False)[0]
        if pose.keypoints is None or len(pose.keypoints) == 0:
            pose = self.pose(frame_bgr, conf=self.conf, imgsz=self.IMGSZ_RETRY, verbose=False)[0]
        person = None
        if pose.keypoints is not None and len(pose.keypoints) > 0:
            person = self._closest_person(pose, best[0] if best else None, frame_bgr.shape)

        if not best:
            # zoomed retry around the rider, else around where the bike last was
            anchor = None
            if person is not None:
                vis = person[person[:, 2] > 0.3]
                if len(vis) >= 4:
                    ext = float(vis[:, 1].max() - vis[:, 1].min())
                    anchor = ((float(vis[:, 0].mean()), float(vis[:, 1].mean()) + 0.3 * ext), 3.5 * max(ext, 40.0))
            if anchor is None and self._last_box is not None and self._box_miss < 20:
                x1, y1, x2, y2 = self._last_box
                anchor = (((x1 + x2) / 2, (y1 + y2) / 2), 3.0 * max(y2 - y1, x2 - x1, 60.0))
            if anchor is not None:
                best = self._roi_detect(frame_bgr, *anchor)

        if best:
            (x1, y1, x2, y2), rec.bike_conf = best
            rec.bike_box = [x1, y1, x2, y2]
            rec.bike_center_y = (y1 + y2) / 2
            rec.bike_height = y2 - y1
            self._last_box, self._box_miss = rec.bike_box, 0
        else:
            self._box_miss += 1

        if person is not None:
            for name, i in KP.items():
                x, y, c = person[i]
                if c > 0.3:
                    rec.keypoints[name] = [float(x), float(y), float(c)]
            self._derive_geometry(rec)
        return rec

    def _closest_person(self, pose_result, bike_box, shape):
        """Pick the rider, not a bystander.

        Anchor = the bike box center when the bike is detected, else the
        rider's hip position from the last confirmed frame. The person whose
        hips are nearest the anchor wins, but only within MAX_JUMP of it --
        otherwise no rider is recorded for this frame. Falling back to "the
        most confident person" is what graded spectators as the rider.
        With no anchor at all (first frames, no bike) the largest skeleton
        is taken: the subject fills more of the frame than the crowd.
        """
        kps = pose_result.keypoints.data.cpu().numpy()  # (n, 17, 3)
        h, w = shape[:2]
        max_jump = 0.25 * math.hypot(w, h)

        def hips(person):
            pts = [person[i] for i in (KP["l_hip"], KP["r_hip"]) if person[i][2] > 0.3]
            return np.mean([p[:2] for p in pts], axis=0) if pts else None

        def extent(person):
            vis = person[person[:, 2] > 0.3]
            if len(vis) < 4:
                return 0.0
            return float((vis[:, 0].max() - vis[:, 0].min()) * (vis[:, 1].max() - vis[:, 1].min()))

        anchor = None
        if bike_box is not None:
            anchor = ((bike_box[0] + bike_box[2]) / 2, (bike_box[1] + bike_box[3]) / 2)
        elif self._last_hip is not None and self._miss < 15:
            anchor = self._last_hip

        chosen = None
        if anchor is None:
            chosen = max(kps, key=extent)
            if extent(chosen) <= 0:
                chosen = None
        else:
            best_d = float("inf")
            for person in kps:
                hp = hips(person)
                if hp is None:
                    continue
                d = math.hypot(hp[0] - anchor[0], hp[1] - anchor[1])
                if d < best_d:
                    chosen, best_d = person, d
            if chosen is not None and best_d > max_jump:
                chosen = None

        if chosen is not None:
            hp = hips(chosen)
            if hp is not None:
                self._last_hip = (float(hp[0]), float(hp[1]))
            self._miss = 0
        else:
            self._miss += 1
        return chosen

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
        if elbow and shoulder and hip:
            rec.shoulder_angle = _angle(elbow, shoulder, hip)
        nose = k.get("nose")
        if nose and shoulder and hip:
            rec.neck_angle = _angle(nose[:2], shoulder, hip)
        if elbow and wrist:
            rec.wrist_angle = math.degrees(math.atan2(wrist[1] - elbow[1],
                                                      abs(wrist[0] - elbow[0]) + 1e-6))
        if knee and ankle:
            rec.ankle_angle = math.degrees(math.atan2(abs(ankle[0] - knee[0]),
                                                      max(ankle[1] - knee[1], 1e-6)))
        if hip and shoulder:
            rec.torso_angle = math.degrees(math.atan2(hip[1] - shoulder[1],
                                                      abs(shoulder[0] - hip[0]) + 1e-6))
        ear = _side_avg(k, "l_ear", "r_ear") or _side_avg(k, "l_eye", "r_eye")
        if ear and nose:
            dx, dy = nose[0] - ear[0], nose[1] - ear[1]
            n = math.hypot(dx, dy)
            if n > 1e-6:
                rec.gaze_angle = math.degrees(math.atan2(dy, abs(dx)))
                rec.gaze_origin = [float(ear[0]), float(ear[1])]
                rec.gaze_vec = [float(dx / n), float(dy / n)]
        if hip and shoulder and rec.bike_box:
            com_x = (hip[0] + shoulder[0]) / 2
            bike_cx = (rec.bike_box[0] + rec.bike_box[2]) / 2
            rec.com_offset_x = com_x - bike_cx


_ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


def detect_orientation(video_path: str | Path, tracker: "BikeRiderTracker",
                       samples: int = 6) -> int:
    """Probe a few frames in each rotation; return the rotation (degrees,
    clockwise) with the most confident person detections.

    Handles footage (e.g. some screen recordings) that decodes with content
    rotated 90/270 degrees but carries no rotation metadata OpenCV can read.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    idxs = [int(total * f) for f in np.linspace(0.1, 0.9, samples)]
    frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if ok:
            frames.append(f)
    cap.release()
    if not frames:
        return 0

    best_deg, best_conf = 0, -1.0
    for deg, code in _ROTATIONS.items():
        total_conf = 0.0
        for f in frames:
            test = cv2.rotate(f, code) if code is not None else f
            pose = tracker.pose(test, conf=tracker.conf, verbose=False)[0]
            if pose.keypoints is not None and len(pose.keypoints) > 0:
                confs = pose.keypoints.data[..., 2].cpu().numpy()
                total_conf += float(confs.max(axis=1).sum()) if confs.size else 0.0
        if total_conf > best_conf:
            best_deg, best_conf = deg, total_conf
    return best_deg


def track_video(video_path: str | Path, out_json: str | Path,
                stride: int = 1, max_frames: int | None = None,
                rotate_deg: int | None = None) -> list[FrameTrack]:
    """Track every `stride`-th frame of a video; write records to JSON.

    rotate_deg: force a rotation (0/90/180/270); None auto-detects from
    which orientation the pose model finds people in most confidently.
    """
    tracker = BikeRiderTracker()
    if rotate_deg is None:
        rotate_deg = detect_orientation(video_path, tracker)
    rot_code = _ROTATIONS.get(rotate_deg % 360)
    if rotate_deg:
        print(f"    detected {rotate_deg}deg rotation, correcting")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    records, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if rot_code is not None:
            frame = cv2.rotate(frame, rot_code)
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
