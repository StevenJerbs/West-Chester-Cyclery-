"""True bike + rider outlines via instance segmentation.

track.py's `annotate()` draws a bounding box for the bike and a stick-figure
skeleton for the rider -- useful for joint angles, but not an outline. This
module runs YOLOv8-seg (bicycle + person classes) to get real silhouette
contours, matched to the same "closest to the rider" logic used elsewhere
(nearest instance to the already-tracked bike box / hip position, so the
outline follows the same subject across frames rather than jumping to
whichever bicycle or person is most confident in a busy scene).
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

BICYCLE_CLASS = 1
PERSON_CLASS = 0

BIKE_COLOR = (255, 220, 60)     # cyan, matches highlights.py's bike box
RIDER_COLOR = (80, 220, 80)     # green, matches highlights.py's skeleton
BIKE_FILL_ALPHA = 0.22
RIDER_FILL_ALPHA = 0.18


class OutlineTracker:
    def __init__(self, seg_weights: str = "yolov8n-seg.pt", conf: float = 0.25):
        from ultralytics import YOLO
        self.seg = YOLO(seg_weights)
        self.conf = conf

    def masks_for_frame(self, frame_bgr, near_point: tuple[float, float] | None = None):
        """Return (bike_mask, rider_mask) as uint8 0/255 arrays sized to the
        frame, or None each if nothing of that class was found. When
        near_point is given, picks the instance whose centroid is closest
        to it (keeps the outline on the same subject frame to frame);
        otherwise picks the largest instance of each class.
        """
        h, w = frame_bgr.shape[:2]
        result = self.seg(frame_bgr, conf=self.conf, verbose=False)[0]
        if result.masks is None or BICYCLE_CLASS not in result.boxes.cls.cpu().numpy().astype(int):
            result = self.seg(frame_bgr, conf=self.conf, imgsz=1280, verbose=False)[0]  # small, distant bike
        bike_mask = rider_mask = None
        if result.masks is None:
            return bike_mask, rider_mask

        classes = result.boxes.cls.cpu().numpy().astype(int)
        masks = result.masks.data.cpu().numpy()  # (n, mh, mw) in [0,1]
        boxes = result.boxes.xyxy.cpu().numpy()

        def pick(cls_id):
            idxs = np.where(classes == cls_id)[0]
            if len(idxs) == 0:
                return None
            if near_point is None:
                best = idxs[np.argmax([boxes[i][2] - boxes[i][0] for i in idxs])]
            else:
                px, py = near_point
                best = min(idxs, key=lambda i: math.hypot(
                    (boxes[i][0] + boxes[i][2]) / 2 - px,
                    (boxes[i][1] + boxes[i][3]) / 2 - py))
            m = masks[best]
            m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
            return (m > 0.5).astype(np.uint8) * 255

        bike_mask = pick(BICYCLE_CLASS)
        rider_mask = pick(PERSON_CLASS)
        return bike_mask, rider_mask


def draw_outline(frame, mask, color, fill_alpha, label=None):
    if mask is None:
        return frame
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return frame
    overlay = frame.copy()
    cv2.drawContours(overlay, contours, -1, color, thickness=cv2.FILLED)
    cv2.addWeighted(overlay, fill_alpha, frame, 1 - fill_alpha, 0, dst=frame)
    cv2.drawContours(frame, contours, -1, color, thickness=3, lineType=cv2.LINE_AA)
    if label:
        x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
        cv2.putText(frame, label, (x, max(15, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return frame


def render_outline_video(video_path: str | Path, out_path: str | Path,
                         track_json: dict | None = None, rotate_deg: int = 0,
                         suspension_meter: bool = True) -> Path:
    """Render a video with true silhouette outlines for the bike and rider.

    track_json (optional, already-loaded dict from track.py's output): if
    given, uses its recorded bike box / hip position each frame to steer
    which segmentation instance the outline follows, and reuses its
    suspension score for the activity meter.
    """
    from track import _ROTATIONS

    tracker = OutlineTracker()
    rot_code = _ROTATIONS.get(rotate_deg % 360)

    frames_by_idx = {}
    times = scores = None
    if track_json is not None:
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

        rec = frames_by_idx.get(i)
        near = None
        if rec and rec.get("bike_box"):
            x1, y1, x2, y2 = rec["bike_box"]
            near = ((x1 + x2) / 2, (y1 + y2) / 2)
        bike_mask, rider_mask = tracker.masks_for_frame(frame, near_point=near)
        draw_outline(frame, rider_mask, RIDER_COLOR, RIDER_FILL_ALPHA, "rider")
        draw_outline(frame, bike_mask, BIKE_COLOR, BIKE_FILL_ALPHA, "bike")

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
