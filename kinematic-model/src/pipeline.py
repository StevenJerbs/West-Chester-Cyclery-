"""End-to-end pipeline: download -> track -> score -> highlights -> finetune.

Usage:
    python pipeline.py https://youtu.be/u2gOY98G0B8
    python pipeline.py <url> --stride 2 --clips 6 --clip-len 5 --no-train

Outputs land in kinematic-model/output/<video_id>/:
    track.json        per-frame bike + rider geometry
    suspension.json   suspension-activity score over time
    highlights/       annotated MP4 clips + peak-frame PNG stills
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def download(url: str, out_dir: Path) -> Path:
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="YouTube URL or local video path")
    ap.add_argument("--stride", type=int, default=1,
                    help="track every Nth frame (default 1)")
    ap.add_argument("--clips", type=int, default=6,
                    help="number of highlight shots to export")
    ap.add_argument("--clip-len", type=float, default=5.0,
                    help="highlight clip length in seconds")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--no-train", action="store_true",
                    help="skip the fine-tuning stage")
    args = ap.parse_args()

    from track import track_video, detect_orientation, BikeRiderTracker
    from suspension import suspension_score, pick_windows
    from highlights import export_highlights

    if args.url.startswith("http"):
        video = download(args.url, ROOT / "data" / "raw")
    else:
        video = Path(args.url)
    vid_id = video.stem
    out = ROOT / "output" / vid_id

    print(f"[1/4] tracking {video.name} ...")
    rotate_deg = detect_orientation(video, BikeRiderTracker())
    track_json = out / "track.json"
    track_video(video, track_json, stride=args.stride, max_frames=args.max_frames,
                rotate_deg=rotate_deg)

    print("[2/4] scoring suspension activity ...")
    score_json = out / "suspension.json"
    times, scores = suspension_score(track_json, score_json)

    print("[3/4] exporting highlight shots ...")
    windows = pick_windows(times, scores, n=args.clips, clip_len_s=args.clip_len)
    manifest = export_highlights(video, track_json, score_json, windows,
                                 out / "highlights", rotate_deg=rotate_deg)
    for m in manifest:
        print(f"    #{m['rank']}  {m['start_s']:7.2f}s - {m['end_s']:7.2f}s"
              f"  score {m['mean_score']:.3f}  -> {m['clip']}")

    if args.no_train:
        print("[4/4] training skipped (--no-train)")
        return

    print("[4/4] continuing model training on this video ...")
    from finetune import build_dataset, finetune
    n = build_dataset(video, track_json, rotate_deg=rotate_deg)
    print(f"    added {n} auto-labeled frames")
    if n:
        finetune()


if __name__ == "__main__":
    main()
