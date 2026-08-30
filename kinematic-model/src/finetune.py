"""Continue training the pose model on frames auto-labeled by the pipeline.

Self-training loop: high-confidence tracking output from each new video is
converted into YOLO-pose labels, and yolov8n-pose is fine-tuned on them.
Runs from the last checkpoint in weights/ if one exists, so each video
continues the previous training rather than starting over.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2

from track import KP

MIN_CONF = 0.6         # only train on confident detections
MIN_KEYPOINTS = 8      # need most of the skeleton visible

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS_DIR = ROOT / "weights"
DATASET_DIR = ROOT / "data" / "auto_labels"


def build_dataset(video_path: str | Path, track_json: str | Path,
                  every_n: int = 10) -> int:
    """Export confident frames as YOLO-pose images + labels. Returns count."""
    data = json.loads(Path(track_json).read_text())
    img_dir = DATASET_DIR / "images" / "train"
    lbl_dir = DATASET_DIR / "labels" / "train"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")
    stem = Path(video_path).stem

    n = 0
    for i, rec in enumerate(data["frames"]):
        if i % every_n:
            continue
        kps = rec.get("keypoints", {})
        if rec.get("bike_conf", 0) < MIN_CONF or len(kps) < MIN_KEYPOINTS:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, rec["frame"])
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]

        xs = [p[0] for p in kps.values()]
        ys = [p[1] for p in kps.values()]
        x1, x2 = max(0, min(xs) - 10), min(w, max(xs) + 10)
        y1, y2 = max(0, min(ys) - 10), min(h, max(ys) + 10)
        cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
        bw, bh = (x2 - x1) / w, (y2 - y1) / h

        parts = [f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"]
        for name in KP:  # canonical COCO order (dict preserves insertion order)
            if name in kps:
                x, y, _ = kps[name]
                parts.append(f"{x / w:.6f} {y / h:.6f} 2")
            else:
                parts.append("0 0 0")

        name = f"{stem}_{rec['frame']:06d}"
        cv2.imwrite(str(img_dir / f"{name}.jpg"), frame)
        (lbl_dir / f"{name}.txt").write_text(" ".join(parts) + "\n")
        n += 1
    cap.release()

    (DATASET_DIR / "dataset.yaml").write_text(
        f"path: {DATASET_DIR}\n"
        "train: images/train\n"
        "val: images/train\n"
        "kpt_shape: [17, 3]\n"
        "names:\n  0: rider\n")
    return n


def latest_checkpoint() -> str:
    if WEIGHTS_DIR.exists():
        ckpts = sorted(WEIGHTS_DIR.glob("kinematic_pose_v*.pt"))
        if ckpts:
            return str(ckpts[-1])
    return "yolov8n-pose.pt"


def finetune(epochs: int = 20, imgsz: int = 640) -> str:
    """Fine-tune from the latest checkpoint; save the next version."""
    from ultralytics import YOLO

    start = latest_checkpoint()
    model = YOLO(start)
    model.train(data=str(DATASET_DIR / "dataset.yaml"),
                epochs=epochs, imgsz=imgsz, project=str(ROOT / "runs"),
                name="kinematic_pose", exist_ok=True)

    WEIGHTS_DIR.mkdir(exist_ok=True)
    existing = sorted(WEIGHTS_DIR.glob("kinematic_pose_v*.pt"))
    version = len(existing) + 1
    out = WEIGHTS_DIR / f"kinematic_pose_v{version:03d}.pt"
    best = ROOT / "runs" / "kinematic_pose" / "weights" / "best.pt"
    out.write_bytes(best.read_bytes())
    print(f"trained from {start} -> {out}")
    return str(out)
