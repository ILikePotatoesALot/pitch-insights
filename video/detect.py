"""Run the tiled detector over the clip (or the calibration frames) and store raw detections.

Everything after detection (pitch mapping, filtering, tracking, teams, events,
the benchmark) works from this file, so the slow part runs once. Resumable: a
frame already in the output file is skipped.

    video\\.venv\\Scripts\\python video\\detect.py clip      # 500 frames, about an hour
    video\\.venv\\Scripts\\python video\\detect.py calib     # 75 frames before the clip
"""

from __future__ import annotations

import argparse
import json
import time

import cv2

import clip
from detector import PERSON, TiledDetector, shirt_colour

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
    args = ap.parse_args()
    out = output_for(args.which)
    out.parent.mkdir(parents=True, exist_ok=True)
    done: set[int] = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {json.loads(line)["frame"] for line in f if line.strip()}
    todo = [fr for fr in frames_for(args.which) if fr not in done]
    print(f"{len(todo)} frames to detect ({len(done)} already done)", flush=True)
    if not todo:
        return

    detector = TiledDetector()
    cap = cv2.VideoCapture(str(clip.VIDEO))
    if not cap.isOpened():
        raise SystemExit(f"can't open {clip.VIDEO}")
    started = time.perf_counter()
    position = -1  # 0-based index of the frame `read` returns next, once known
    with open(out, "a", encoding="utf-8") as f:
        for n, frame in enumerate(todo, 1):
            index = frame - 1
            if 0 <= index - position <= 50:  # close ahead: decode forwards, which is exact
                while position < index:
                    cap.grab()
                    position += 1
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                position = index
            ok, bgr = cap.read()
            position += 1
            if not ok:
                raise SystemExit(f"can't read frame {frame}")
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
