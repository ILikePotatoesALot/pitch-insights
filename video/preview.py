"""Draw the video path's output on the clip, for checking by eye and for the demo.

Writes data/video/117093/preview.mp4 (git-ignored) at 5 frames a second: our
tracked players (team colour and track ID), the ball, and SoccerTrack's ground
truth as small dots labelled by side and number ("Left #7"), never by name.
Run after process.py.

    video\\.venv\\Scripts\\python video\\preview.py
"""

from __future__ import annotations

import json

import cv2
import numpy as np

import clip
from calibration import Calibration
from pitch_insights.video.soccertrack import from_our_frame

COLOURS = {"L": (235, 140, 30), "R": (245, 245, 245), None: (0, 200, 255)}  # BGR
CROP_TOP, CROP_BOTTOM = 40, 840
OUT = clip.WORK / "preview.mp4"


def main() -> None:
    cal = Calibration.load(clip.CALIBRATION)
    frames = [json.loads(line) for line in clip.FRAMES_OUT.read_text(encoding="utf-8").splitlines()]
    gt = {json.loads(line)["frame"]: json.loads(line)["objects"] for line in clip.GSR_CLIP.read_text(encoding="utf-8").splitlines()}
    by_frame = {round(f["t"] * clip.FPS) + 1: f for f in frames}
    outline = cal.pitch_outline().astype(np.int32)

    cap = cv2.VideoCapture(str(clip.VIDEO))
    cap.set(cv2.CAP_PROP_POS_FRAMES, clip.FIRST_FRAME - 1)
    writer = None
    for frame in range(clip.FIRST_FRAME, clip.LAST_FRAME + 1):
        ok, img = cap.read()
        if not ok:
            break
        if frame not in by_frame:
            continue
        msg = by_frame[frame]
        cv2.polylines(img, [outline], True, (0, 255, 255), 1)
        for o in gt.get(frame, []):
            u, v = cal.to_image([(o["x_st"], o["y_st"])])[0]
            label = f"{o['side'].capitalize()} #{o['jersey']}"
            cv2.circle(img, (int(u), int(v)), 4, (60, 60, 230), -1)
            cv2.putText(img, label, (int(u) + 5, int(v) + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 230), 1)
        for p in msg["players"]:
            team = p["team_id"]
            xs, ys = from_our_frame(p["x"], p["y"], (team or msg["ref_team_id"]) == "L")
            u, v = cal.to_image([(xs, ys)])[0]
            cv2.ellipse(img, (int(u), int(v)), (16, 6), 0, 0, 360, COLOURS[team], 2)
            cv2.putText(img, p["id"], (int(u) - 18, int(v) - 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOURS[team], 2)
        if msg["ball"]:
            xs, ys = from_our_frame(msg["ball"]["x"], msg["ball"]["y"], msg["ref_team_id"] == "L")
            u, v = cal.to_image([(xs, ys)])[0]
            cv2.circle(img, (int(u), int(v)), 12, (0, 0, 255), 2)
        cv2.putText(img, f"SoccerTrack v2 (CC BY 4.0), match {clip.MATCH}, {msg['clock']}  "
                    "rings: our tracking   red dots: ground truth",
                    (20, CROP_BOTTOM - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        out = img[CROP_TOP:CROP_BOTTOM]
        if writer is None:
            writer = cv2.VideoWriter(str(OUT), cv2.VideoWriter_fourcc(*"mp4v"), clip.FPS / clip.STRIDE,
                                     (out.shape[1], out.shape[0]))
        writer.write(out)
    if writer:
        writer.release()
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
