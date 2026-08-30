"""Find riding highlights inside a full-length video (a race run, a vlog,
a multi-hour ride), where running the full tracker frame-by-frame would
take hours.

Two-stage funnel:
  1. coarse_motion_scan -- cheap, ML-free: decode at ~1 frame/sec via
     ffmpeg (handles codecs cv2 can't, e.g. AV1), downscaled, and measure
     frame-to-frame pixel motion. This is a fast proxy for "the camera is
     moving" (riding) vs. static or talking-head segments. ~13x realtime
     on CPU, so a 90-minute video scans in ~7 minutes.
  2. pick_candidate_times + extract_clip -- take the top motion peaks
     (spaced apart so they sample different parts of the video), cut a
     short clip around each with ffmpeg, and hand those to the real
     pipeline (track_video / suspension_score / joint_analysis) for
     verification. Motion energy alone can't tell a bike from a car or a
     camera pan, so real bike+pose detection on the short candidate clips
     is what actually confirms a shot is worth keeping -- always inspect
     candidates before treating them as verified highlights; a source
     video can contain unrelated spliced-in footage that a motion scan
     alone will not catch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
import numpy as np


def coarse_motion_scan(video_path: str | Path, sample_hz: float = 1.0,
                       resize: tuple[int, int] = (320, 180)) -> np.ndarray:
    """Per-second motion-energy signal for the whole video. No ML."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    w, h = resize
    cmd = [ff, "-loglevel", "error", "-i", str(video_path),
           "-vf", f"fps={sample_hz},scale={w}:{h}",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    frame_size = w * h
    frames = []
    while True:
        buf = proc.stdout.read(frame_size)
        if len(buf) < frame_size:
            break
        frames.append(np.frombuffer(buf, dtype=np.uint8).reshape(h, w))
    proc.wait()
    if len(frames) < 2:
        return np.zeros(len(frames))
    arr = np.stack(frames).astype(np.float32)
    diffs = np.abs(np.diff(arr, axis=0)).mean(axis=(1, 2))
    return np.concatenate([[diffs[0]], diffs])


def pick_candidate_times(motion: np.ndarray, n: int = 12, smooth_s: int = 5,
                         min_gap_s: int = 180) -> list[tuple[int, float]]:
    """Top local motion peaks, spaced >= min_gap_s apart (seconds).

    Returns [(time_s, score)] sorted by score descending.
    """
    win = max(1, smooth_s)
    kernel = np.ones(win) / win
    smooth = np.convolve(motion, kernel, mode="same")

    order = np.argsort(smooth)[::-1]
    used = np.zeros(len(smooth), dtype=bool)
    picked = []
    for i in order:
        if used[i]:
            continue
        picked.append((int(i), float(smooth[i])))
        lo, hi = max(0, i - min_gap_s), min(len(smooth), i + min_gap_s)
        used[lo:hi] = True
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda x: -x[1])


def extract_clip(video_path: str | Path, out_path: str | Path,
                 center_s: float, clip_len_s: float = 12.0) -> Path:
    """Cut and re-encode a clip to H.264 (cv2 can't read some source
    codecs like AV1 directly, so downstream tracking needs this)."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    start = max(0, center_s - clip_len_s / 2)
    cmd = [ff, "-y", "-loglevel", "error", "-ss", str(start), "-i", str(video_path),
           "-t", str(clip_len_s), "-c:v", "libx264", "-crf", "20",
           "-pix_fmt", "yuv420p", "-an", str(out_path)]
    subprocess.run(cmd, check=True)
    return Path(out_path)


def find_candidate_clips(video_path: str | Path, out_dir: str | Path,
                         n: int = 12, clip_len_s: float = 12.0,
                         min_gap_s: int = 180) -> list[dict]:
    """Full funnel stage 1+2: scan, pick peaks, extract clips.

    Returns a manifest of extracted clips; run the normal pipeline
    (track_video / suspension_score / highlights / joint_analysis) on
    each to confirm real bike+rider presence before treating any as a
    verified highlight -- inspect a peak frame from each, since motion
    energy alone cannot distinguish riding from an unrelated spliced-in
    scene or a camera pan.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    motion = coarse_motion_scan(video_path)
    candidates = pick_candidate_times(motion, n=n, min_gap_s=min_gap_s)

    manifest = []
    for t, score in candidates:
        clip_path = out_dir / f"cand_{t:05d}s.mp4"
        extract_clip(video_path, clip_path, center_s=t, clip_len_s=clip_len_s)
        manifest.append({"time_s": t, "motion_score": score, "clip": str(clip_path)})
    return manifest
