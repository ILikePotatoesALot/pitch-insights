"""Run the tiled detector over the clip (or the calibration frames) and store raw detections.

Everything after detection (pitch mapping, filtering, tracking, teams, events,
the benchmark) works from this file, so the slow part runs once. Resumable: a
frame already in the output file is skipped.

    video\\.venv\\Scripts\\python video\\detect.py clip      # 500 frames, about an hour on a CPU
    video\\.venv\\Scripts\\python video\\detect.py calib     # 75 frames before the clip

With fine-tuned weights (see video/finetune/README.md), in PowerShell:

    $env:VIDEO_TAG = "_ft"
    video\\.venv\\Scripts\\python video\\detect.py clip --weights path\\to\\checkpoint_best_total.pth
"""

from __future__ import annotations

import argparse
import json
import time

import clip
from detector import PERSON, TiledDetector, shirt_colour
from framesource import read_frames

CALIB_DETECT_STRIDE = 750  # one frame every 30 s before the clip


def frames_for(which: str) -> list[int]:
    if which == "clip":
        return list(clip.clip_frames())
    return list(range(1, clip.FIRST_FRAME - clip.FPS * 10, CALIB_DETECT_STRIDE))


def output_for(which: str):
    return clip.DETECTIONS if which == "clip" else clip.DETECTIONS_CALIB


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["clip", "calib"])
    ap.add_argument("--weights", help="a fine-tuned RF-DETR checkpoint for people (needs VIDEO_TAG, for example _ft)")
    args = ap.parse_args()
    if args.weights and not clip.TAG:
        raise SystemExit("with --weights, set VIDEO_TAG (for example _ft) so the baseline's files aren't mixed in")
    out = output_for(args.which)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {row["frame"] for row in clip.read_jsonl(out, repair=True)}
    todo = [fr for fr in frames_for(args.which) if fr not in done]
    print(f"{len(todo)} frames to detect ({len(done)} already done)", flush=True)
    if not todo:
        return

    detector = TiledDetector(args.weights)
    meta = detector.describe()
    if clip.DETECTOR_META.exists() and json.loads(clip.DETECTOR_META.read_text(encoding="utf-8"))["weights"] != meta["weights"]:
        raise SystemExit(f"{out.name} was made by other weights: use another VIDEO_TAG, or delete it")
    clip.DETECTOR_META.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    started = time.perf_counter()
    with open(out, "a", encoding="utf-8") as f:
        for n, (frame, bgr) in enumerate(read_frames(clip.VIDEO, todo), 1):
            t0 = time.perf_counter()
            dets = detector.detect(bgr)
            row = {
                "frame": frame,
                "seconds": round(time.perf_counter() - t0, 2),
                "detections": [
                    {
                        "box": [round(v, 1) for v in d.box],
                        "score": round(d.score, 3),
                        "class_id": d.class_id,
                        "colour": shirt_colour(bgr, d.box) if d.class_id == PERSON else None,
                    }
                    for d in dets
                ],
            }
            f.write(json.dumps(row) + "\n")
            f.flush()
            if n % 10 == 0 or n == len(todo):
                rate = (time.perf_counter() - started) / n
                print(f"{n}/{len(todo)} frames, {rate:.1f} s a frame, "
                      f"about {rate * (len(todo) - n) / 60:.0f} min left", flush=True)


if __name__ == "__main__":
    main()
