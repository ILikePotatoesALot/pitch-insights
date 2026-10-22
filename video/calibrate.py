"""Fit the image-to-pitch mapping from frames before the clip.

1. A first mapping from SoccerTrack's own boxes (bottom middle) to its pitch
   positions, only to pair our detections with the ground truth.
2. The mapping actually used: from *our detected feet* (bottom middle of the
   RF-DETR box) to the ground-truth positions. SoccerTrack's boxes sit 10-40 px
   off the players, so fitting on them would bias every position.

Only frames before the clip are used, so the clip's benchmark stays honest.
Polynomial degree is chosen by holding out every other calibration frame.

    video\\.venv\\Scripts\\python video\\calibrate.py
"""

from __future__ import annotations

import json

import numpy as np

import clip
from calibration import Calibration, fit_image_to_pitch, fit_pitch_to_image
from detector import PERSON
from pitch_insights.video.bench import match_points

ASSOCIATE_RADIUS_M = 3.0


def main() -> None:
    gt = json.loads(clip.CALIB_PAIRS.read_text(encoding="utf-8"))["pairs"]
    gt_by_frame: dict[int, list[list[float]]] = {}
    for frame, u, v, x, y in gt:
        gt_by_frame.setdefault(int(frame), []).append([u, v, x, y])
    arr = np.array([[u, v, x, y] for rows in gt_by_frame.values() for u, v, x, y in rows])
    first = fit_image_to_pitch(arr[:, :2], arr[:, 2:], 5)

    pairs = []  # frame, u, v, x, y
    with open(clip.DETECTIONS_CALIB, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    for row in rows:
        truth = gt_by_frame.get(row["frame"])
        if not truth:
            continue
        feet = np.array([[(d["box"][0] + d["box"][2]) / 2, d["box"][3]] for d in row["detections"]
                         if d["class_id"] == PERSON and d["score"] >= clip.PERSON_MIN_SCORE]).reshape(-1, 2)
        if not len(feet):
            continue
        guess = first(feet)
        for i, j, _ in match_points([tuple(p) for p in guess], [(t[2], t[3]) for t in truth], ASSOCIATE_RADIUS_M):
            pairs.append([row["frame"], feet[i][0], feet[i][1], truth[j][2], truth[j][3]])
    p = np.array(pairs)
    print(f"{len(rows)} calibration frames, {len(p)} detection-to-truth pairs")

    frames = np.unique(p[:, 0])
    held = np.isin(p[:, 0], frames[1::2])
    results = {}
    for degree in (3, 4, 5):
        m = fit_image_to_pitch(p[~held, 1:3], p[~held, 3:], degree)
        err = np.linalg.norm(m(p[held, 1:3]) - p[held, 3:], axis=1)
        results[degree] = {"mean_m": round(float(err.mean()), 3), "median_m": round(float(np.median(err)), 3)}
        print(f"degree {degree}: held-out error mean {err.mean():.2f} m, median {np.median(err):.2f} m")
    degree = min(results, key=lambda d: results[d]["mean_m"])

    cal = Calibration(fit_image_to_pitch(p[:, 1:3], p[:, 3:], degree), fit_pitch_to_image(p[:, 3:], p[:, 1:3], degree))
    back = np.linalg.norm(cal.to_image(p[:, 3:]) - p[:, 1:3], axis=1)
    cal.save(clip.CALIBRATION, {
        "method": "2-D polynomial, our detected feet (RF-DETR box bottom middle) to SoccerTrack GSR pitch positions",
        "frames": f"{len(frames)} frames before the clip, one every 30 s (frames {int(frames[0])}-{int(frames[-1])})",
        "pairs": len(p),
        "degree": degree,
        "held_out_by_degree": results,
        "pitch_to_image_error_px_mean": round(float(back.mean()), 1),
        "coordinates": "SoccerTrack metres: origin at the centre spot, x to the right goal, y towards the camera",
    })
    print(f"chose degree {degree}; pitch-to-image error {back.mean():.1f} px; wrote {clip.CALIBRATION}")


if __name__ == "__main__":
    main()
