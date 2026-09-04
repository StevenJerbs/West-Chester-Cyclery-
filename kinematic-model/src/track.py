"""Bike + rider tracking for the downhill kinematic visual model.

Runs up to three YOLOv8 models per frame:
  - weights/bikekp_v4_fullframe.pt -> DH bike box + 4 bike keypoints (front_axle,
    rear_axle, fork_crown, bottom_bracket). Trained on downhill footage (mtbkin
    project); primary bike detector when present.
  - yolov8n.pt        -> bicycle bounding box (COCO class 1), fallback detector
  - yolov8n-pose.pt   -> rider keypoints (COCO 17-keypoint skeleton)
Both the bike and the rider get a zoomed retry on a crop around where the other
one is (or was last seen) when the full-frame pass misses them.

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

# bike keypoints from the DH bike model, in its output order
BIKE_KP = ["front_axle", "rear_axle", "fork_crown", "bottom_bracket"]
BIKE_EDGES = [("front_axle", "fork_crown"), ("fork_crown", "bottom_bracket"),
              ("bottom_bracket", "rear_axle"), ("front_axle", "rear_axle")]

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
    bike_kps: dict = field(default_factory=dict)  # name -> [x, y, conf], DH bike model only
    bike_source: str | None = None        # bikekp | coco | bikekp_roi | coco_roi
    pose_source: str | None = None        # full | roi
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
    IMGSZ_BIKE_KP = 1024      # the DH bike model was trained full-frame at 1024
    CONF_STRONG = 0.5         # a bike this confident stands on its own; weaker ones need a rider or continuity

    def __init__(self, det_weights: str = "yolov8n.pt",
                 pose_weights: str = "yolov8n-pose.pt", conf: float = 0.25,
                 bike_kp_weights: str | None = "auto"):
        from ultralytics import YOLO  # imported lazily; heavy dependency
        self.det = YOLO(det_weights)
        self.pose = YOLO(pose_weights)
        self.conf = conf
        # DH-specific bike model (mtbkin bikekp v4). "auto" picks it up from
        # weights/ when present and silently falls back to COCO-only otherwise.
        # The crop variant was trained on 640-px bike crops and serves the
        # zoomed retry.
        self.bike_kp = None
        self.bike_kp_crop = None
        if bike_kp_weights == "auto":
            import os
            wdir = Path(__file__).resolve().parents[1] / "weights"
            full, crop = wdir / "bikekp_v4_fullframe.pt", wdir / "bikekp_v4_crop.pt"
            # BIKEKP_WEIGHTS=<path> swaps in a candidate checkpoint without renaming files (used for A/B evals)
            env = os.environ.get("BIKEKP_WEIGHTS")
            bike_kp_weights = env if env and Path(env).exists() else (str(full) if full.exists() else None)
            if crop.exists():
                self.bike_kp_crop = YOLO(str(crop))
        if bike_kp_weights:
            self.bike_kp = YOLO(bike_kp_weights)
        self._last_hip = None   # rider identity continuity across frames
        self._last_ext = None   # rider skeleton extent (px), sizes the pose retry crop
        self._miss = 0          # frames since the rider was last confirmed
        self._last_box = None   # last bike box, for the zoomed retry
        self._box_miss = 0
        self._since_support = 99  # frames since a rider was last seen standing on the tracked bike

    # ------------------------------------------------------------ detection helpers
    def _best_bike(self, det, offset=(0, 0), scale=1.0):
        """Best COCO 'bicycle' box -> (box, conf, {}) or None."""
        best = None
        for box in det.boxes:
            if int(box.cls) == BICYCLE_CLASS:
                c = float(box.conf)
                if best is None or c > best[1]:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    best = ([x1 / scale + offset[0], y1 / scale + offset[1],
                             x2 / scale + offset[0], y2 / scale + offset[1]], c, {})
        return best

    def _best_bike_kp(self, res, offset=(0, 0), scale=1.0):
        """Best DH-model bike -> (box, conf, keypoints) or None."""
        if res is None or res.boxes is None or len(res.boxes) == 0:
            return None
        j = int(res.boxes.conf.argmax())
        c = float(res.boxes.conf[j])
        x1, y1, x2, y2 = res.boxes.xyxy[j].tolist()
        box = [x1 / scale + offset[0], y1 / scale + offset[1],
               x2 / scale + offset[0], y2 / scale + offset[1]]
        kps = {}
        if res.keypoints is not None and len(res.keypoints) > j:
            arr = res.keypoints.data[j].cpu().numpy()
            for name, (x, y, kc) in zip(BIKE_KP, arr):
                if kc > 0.3 and (x > 0 or y > 0):
                    kps[name] = [float(x / scale + offset[0]), float(y / scale + offset[1]), float(kc)]
        return box, c, kps

    def _plausible(self, best, frame_shape, strict=False):
        """Reject boxes whose size is out of line with the bike we were just
        tracking (a low-confidence hit on a tree or a bystander's bike) or
        that swallow most of the frame. Confident full-frame hits pass."""
        if best is None:
            return None
        box, conf = best[0], best[1]
        h, w = frame_shape[:2]
        bw, bh = box[2] - box[0], box[3] - box[1]
        if bw <= 2 or bh <= 2 or bw > 0.9 * w or bh > 0.9 * h:
            return None
        if not strict and conf >= 0.5:
            return best
        if self._last_box is not None and self._box_miss < 20:
            lx1, ly1, lx2, ly2 = self._last_box
            last = max(lx2 - lx1, ly2 - ly1, 1.0)
            ratio = max(bw, bh) / last
            if not (0.4 <= ratio <= 2.5):
                return None
        return best

    @staticmethod
    def _kp_plausible(best):
        """Do the DH model's own keypoints describe a bike? At least two
        confident points, and any axle it reports lies inside the box and in
        its lower 70%. A COCO box (no keypoints) is neutral: returns None."""
        if best is None:
            return None
        box, _, kps = best
        if not kps:
            return None
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        conf = [k for k, v in kps.items() if v[2] > 0.5]
        if len(conf) < 2:
            return False
        for name in ("front_axle", "rear_axle"):
            v = kps.get(name)
            if v is None or v[2] <= 0.5:
                continue
            x, y = v[0], v[1]
            if not (x1 - 0.1 * bw <= x <= x2 + 0.1 * bw and y1 + 0.3 * bh <= y <= y2 + 0.1 * bh):
                return False
        return True

    def _is_strong(self, best):
        """Confident enough to stand without a rider: high score and, for the
        DH model, keypoints that look like a bike."""
        if best is None or best[1] < self.CONF_STRONG:
            return False
        return self._kp_plausible(best) is not False

    def _detect_bike_full(self, frame_bgr):
        if self.bike_kp is not None:
            res = self.bike_kp(frame_bgr, conf=self.conf, imgsz=self.IMGSZ_BIKE_KP, verbose=False)[0]
            best = self._plausible(self._best_bike_kp(res), frame_bgr.shape)
            if best:
                return best, "bikekp"
        for imgsz in (self.IMGSZ, self.IMGSZ_RETRY):
            det = self.det(frame_bgr, conf=self.conf, imgsz=imgsz, verbose=False)[0]
            best = self._plausible(self._best_bike(det), frame_bgr.shape)
            if best:
                return best, "coco"
        return None, None

    @staticmethod
    def _crop(frame_bgr, center, size):
        """Square crop around center, upscaled to 640 if smaller. Returns
        (crop, x0, y0, scale) with scale = crop_px / source_px."""
        h, w = frame_bgr.shape[:2]
        size = int(max(224, min(size, min(h, w))))
        cx, cy = center
        x0 = int(np.clip(cx - size / 2, 0, w - size))
        y0 = int(np.clip(cy - size / 2, 0, h - size))
        crop = frame_bgr[y0:y0 + size, x0:x0 + size]
        scale = 640.0 / size
        if scale > 1.0:
            crop = cv2.resize(crop, (640, 640), interpolation=cv2.INTER_CUBIC)
        else:
            scale = 1.0
        return crop, x0, y0, scale

    def _roi_detect(self, frame_bgr, center, size):
        """Zoomed retry for a small, distant bike: crop a square around the
        rider (or the last bike box), upscale it so the bike is a few hundred
        px, and run the detectors on that. Coordinates are mapped back.
        Returns (best, source)."""
        crop, x0, y0, scale = self._crop(frame_bgr, center, size)
        conf = max(0.15, self.conf - 0.1)
        cands = []
        kp_model = self.bike_kp_crop or self.bike_kp
        if kp_model is not None:
            res = kp_model(crop, conf=conf, imgsz=640, verbose=False)[0]
            b = self._best_bike_kp(res, offset=(x0, y0), scale=scale)
            if b:
                cands.append((b, "bikekp_roi"))
        det = self.det(crop, conf=conf, imgsz=640, verbose=False)[0]
        b = self._best_bike(det, offset=(x0, y0), scale=scale)
        if b:
            cands.append((b, "coco_roi"))
        cands = [(self._plausible(b, frame_bgr.shape, strict=True), src) for b, src in cands]
        cands = [c for c in cands if c[0] is not None]
        if not cands:
            return None, None
        # highest confidence wins; on a near tie prefer the DH model (it carries keypoints)
        cands.sort(key=lambda t: (t[0][1] + (0.05 if t[1] == "bikekp_roi" else 0.0)), reverse=True)
        return cands[0]

    def _pose_kps(self, frame_bgr):
        """Full-frame pose pass -> (n, 17, 3) array in frame coords, or None."""
        pose = self.pose(frame_bgr, conf=self.conf, imgsz=self.IMGSZ, verbose=False)[0]
        if pose.keypoints is None or len(pose.keypoints) == 0:
            pose = self.pose(frame_bgr, conf=self.conf, imgsz=self.IMGSZ_RETRY, verbose=False)[0]
        if pose.keypoints is None or len(pose.keypoints) == 0:
            return None
        return pose.keypoints.data.cpu().numpy()

    def _roi_pose(self, frame_bgr, center, size):
        """Zoomed pose retry around the bike (or where the rider was last
        seen). A rider that is ~60 px tall in a 1080p chase frame is below
        what yolov8n-pose resolves at 640/1280; upscaling the crop fixes that.
        Returns keypoints mapped back to frame coords, or None."""
        crop, x0, y0, scale = self._crop(frame_bgr, center, size)
        pose = self.pose(crop, conf=max(0.15, self.conf - 0.1), imgsz=640, verbose=False)[0]
        if pose.keypoints is None or len(pose.keypoints) == 0:
            return None
        kps = pose.keypoints.data.cpu().numpy().copy()
        kps[..., 0] = kps[..., 0] / scale + x0
        kps[..., 1] = kps[..., 1] / scale + y0
        return kps

    @staticmethod
    def _supported(box, person):
        """Is a credible rider standing on this bike? Hips or ankles over the
        box: within a quarter box-width sideways, up to 0.6 box-heights above
        the top (hips of a standing rider), a fifth below the bottom."""
        if person is None:
            return False
        vis = person[person[:, 2] > 0.3]
        if len(vis) < 7 or float(vis[:, 2].mean()) < 0.5:
            return False
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        pts = [person[i] for i in (KP["l_hip"], KP["r_hip"], KP["l_ankle"], KP["r_ankle"]) if person[i][2] > 0.3]
        for x, y, _ in pts:
            if x1 - 0.25 * bw <= x <= x2 + 0.25 * bw and y1 - 0.6 * bh <= y <= y2 + 0.2 * bh:
                return True
        return False

    def _continuous(self, box):
        """Does this box continue the bike we were tracking a moment ago?
        Continuity is only trusted while a rider has recently been seen on
        that bike; otherwise one false box would carry itself forever."""
        if self._last_box is None or self._box_miss >= 20 or self._since_support >= 15:
            return False
        lx1, ly1, lx2, ly2 = self._last_box
        last = max(lx2 - lx1, ly2 - ly1, 1.0)
        d = math.hypot((box[0] + box[2]) / 2 - (lx1 + lx2) / 2, (box[1] + box[3]) / 2 - (ly1 + ly2) / 2)
        ratio = max(box[2] - box[0], box[3] - box[1]) / last
        return d < 1.0 * last * (1 + 0.1 * self._box_miss) and 0.5 <= ratio <= 2.0

    @staticmethod
    def _rider_anchor(person):
        """(center, crop_size) for a bike search below the rider, or None."""
        if person is None:
            return None
        vis = person[person[:, 2] > 0.3]
        if len(vis) < 4:
            return None
        ext = float(vis[:, 1].max() - vis[:, 1].min())
        return ((float(vis[:, 0].mean()), float(vis[:, 1].mean()) + 0.3 * ext), 3.5 * max(ext, 40.0))

    # ------------------------------------------------------------------ per frame
    def track_frame(self, frame_bgr, idx: int, time_s: float) -> FrameTrack:
        rec = FrameTrack(frame=idx, time_s=time_s)
        shape = frame_bgr.shape

        # 1. bike candidate, full frame (DH model first, COCO fallback)
        best, src = self._detect_bike_full(frame_bgr)
        strong = self._is_strong(best)

        # 2. rider, full frame. A confident bike anchors the choice; a weak
        #    bike candidate must not, or a hit on a tree picks a phantom rider.
        person = None
        kps_all = self._pose_kps(frame_bgr)
        if kps_all is not None:
            person = self._closest_person(kps_all, best[0] if strong else None, shape)

        # weak bike candidates need corroboration: a rider standing on them or
        # continuity with the bike we were tracking a moment ago
        if best and not strong:
            ok = self._supported(best[0], person) or (self._kp_plausible(best) is not False and self._continuous(best[0]))
            if not ok:
                best, src = None, None
        if best and not strong and kps_all is not None and person is None:
            person = self._closest_person(kps_all, best[0], shape)
        if person is not None:
            rec.pose_source = "full"

        # 3. bike zoomed retry around the rider, else around the last bike box
        if not best:
            anchor = self._rider_anchor(person)
            if anchor is None and self._last_box is not None and self._box_miss < 20:
                x1, y1, x2, y2 = self._last_box
                anchor = (((x1 + x2) / 2, (y1 + y2) / 2), 3.0 * max(y2 - y1, x2 - x1, 60.0))
            if anchor is not None:
                cand, csrc = self._roi_detect(frame_bgr, *anchor)
                # an upscaled crop inflates confidence, so a retry hit never stands alone
                if cand and (self._supported(cand[0], person) or (self._kp_plausible(cand) is not False and self._continuous(cand[0]))):
                    best, src = cand, csrc

        # 4. rider zoomed retry around the bike, else around the last hips
        if person is None:
            panchor = None
            if best:
                x1, y1, x2, y2 = best[0]
                ext = max(y2 - y1, x2 - x1, 80.0)
                # the rider stands over the bike: centre the crop a little above the box
                panchor = (((x1 + x2) / 2, (y1 + y2) / 2 - 0.35 * (y2 - y1)), 3.0 * ext)
            elif self._last_hip is not None and self._miss < 15:
                panchor = (self._last_hip, 3.0 * max(self._last_ext or 120.0, 80.0))
            if panchor is not None:
                kps_roi = self._roi_pose(frame_bgr, *panchor)
                if kps_roi is not None:
                    person = self._closest_person(kps_roi, best[0] if best else None, shape)
                    if person is not None:
                        rec.pose_source = "roi"

        # rider continuity state
        if person is not None:
            hp = self._hips(person)
            if hp is not None:
                self._last_hip = (float(hp[0]), float(hp[1]))
            vis = person[person[:, 2] > 0.3]
            if len(vis) >= 4:
                self._last_ext = float(vis[:, 1].max() - vis[:, 1].min())
            self._miss = 0
        else:
            self._miss += 1

        if best:
            (x1, y1, x2, y2), rec.bike_conf, rec.bike_kps = best
            rec.bike_box = [x1, y1, x2, y2]
            rec.bike_center_y = (y1 + y2) / 2
            rec.bike_height = y2 - y1
            rec.bike_source = src
            self._last_box, self._box_miss = rec.bike_box, 0
            self._since_support = 0 if self._supported(rec.bike_box, person) else self._since_support + 1
        else:
            self._box_miss += 1
            self._since_support += 1

        if person is not None:
            for name, i in KP.items():
                x, y, c = person[i]
                if c > 0.3:
                    rec.keypoints[name] = [float(x), float(y), float(c)]
            self._derive_geometry(rec)
        return rec

    @staticmethod
    def _hips(person):
        pts = [person[i] for i in (KP["l_hip"], KP["r_hip"]) if person[i][2] > 0.3]
        return np.mean([p[:2] for p in pts], axis=0) if pts else None

    def _closest_person(self, kps, bike_box, shape):
        """Pick the rider, not a bystander. `kps` is an (n, 17, 3) array.

        Anchor = the bike box center when the bike is detected, else the
        rider's hip position from the last confirmed frame. The person whose
        hips are nearest the anchor wins, but only within MAX_JUMP of it --
        otherwise no rider is recorded for this frame. Falling back to "the
        most confident person" is what graded spectators as the rider.
        With no anchor at all (first frames, no bike) the largest skeleton
        is taken: the subject fills more of the frame than the crowd.
        Pure selection: continuity state is updated by track_frame.
        """
        h, w = shape[:2]
        max_jump = 0.25 * math.hypot(w, h)
        if bike_box is not None:
            # the rider stands on the bike: hips within ~1.5 bike sizes of its centre
            max_jump = min(max_jump, max(1.5 * max(bike_box[2] - bike_box[0], bike_box[3] - bike_box[1]), 0.08 * math.hypot(w, h)))

        def credible(person):
            """A skeleton, not a texture: enough visible joints, decent confidence."""
            vis = person[person[:, 2] > 0.3]
            return len(vis) >= 5 and float(vis[:, 2].mean()) >= 0.45

        kps = [p for p in kps if credible(p)]
        if not kps:
            return None

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
            # nothing to anchor on: only a clearly articulated skeleton may start a track
            strong = [p for p in kps if (p[:, 2] > 0.3).sum() >= 7 and float(p[p[:, 2] > 0.3][:, 2].mean()) >= 0.5]
            chosen = max(strong, key=extent) if strong else None
            if chosen is not None and extent(chosen) <= 0:
                chosen = None
        else:
            best_d = float("inf")
            for person in kps:
                hp = self._hips(person)
                if hp is None:
                    continue
                d = math.hypot(hp[0] - anchor[0], hp[1] - anchor[1])
                if d < best_d:
                    chosen, best_d = person, d
            if chosen is not None and best_d > max_jump:
                chosen = None
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
    samples = max(samples, 10)
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

    scores = {}
    for deg, code in _ROTATIONS.items():
        total_conf = 0.0
        for f in frames:
            test = cv2.rotate(f, code) if code is not None else f
            pose = tracker.pose(test, conf=tracker.conf, verbose=False)[0]
            if pose.keypoints is not None and len(pose.keypoints) > 0:
                confs = pose.keypoints.data[..., 2].cpu().numpy()
                total_conf += float(confs.max(axis=1).sum()) if confs.size else 0.0
        scores[deg] = total_conf
    # Upright is the prior. A banked FPV frame can score a little higher
    # flipped (sky at the bottom looks like ground), and processing a whole
    # run upside down costs everything downstream, so only rotate when a
    # rotation wins by a clear margin.
    best_deg = max(scores, key=scores.get)
    if best_deg != 0 and scores[best_deg] < 1.6 * max(scores[0], 1e-6):
        return 0
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
