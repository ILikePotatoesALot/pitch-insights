"""Stream the 2.7 GB GSR file once and keep only what the video path needs.

- The clip's ground truth at 5 frames a second (for the benchmark).
- Calibration pairs, image point to pitch metres, from frames *before* the clip
  only, so the clip is never used to fit the mapping it is scored with.

Pure Python: run it with either environment. Takes a few minutes.

    backend\\.venv\\Scripts\\python video\\extract_gsr.py
"""

from __future__ import annotations

import json
import time

import clip
from pitch_insights.video.soccertrack import iter_gsr


def main() -> None:
    clip.WORK.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    wanted = set(clip.clip_frames())
    by_frame: dict[int, list[dict]] = {}
    pairs: list[list[float]] = []
    for obj in iter_gsr(clip.GSR, last_frame=clip.LAST_FRAME):
        if obj.frame in wanted:
            by_frame.setdefault(obj.frame, []).append({
                "track_id": obj.track_id, "role": obj.role, "side": obj.side,
                "jersey": obj.jersey, "x_st": obj.x_st, "y_st": obj.y_st, "box": obj.box,
            })
        elif obj.frame < clip.FIRST_FRAME and obj.frame % clip.CALIB_STRIDE == 1 and obj.box:
            x, y, w, h = obj.box
            # Anchor: bottom middle of the box, where the feet are.
            pairs.append([obj.frame, x + w / 2, y + h, obj.x_st, obj.y_st])
    with open(clip.GSR_CLIP, "w", encoding="utf-8") as f:
        for frame in sorted(wanted):
            f.write(json.dumps({"frame": frame, "objects": by_frame.get(frame, [])}) + "\n")
    with open(clip.CALIB_PAIRS, "w", encoding="utf-8") as f:
        json.dump({"columns": ["frame", "u", "v", "x_st", "y_st"], "anchor": "box bottom middle", "pairs": pairs}, f)
    print(f"{len(by_frame)} clip frames, {len(pairs)} calibration pairs, "
          f"{time.perf_counter() - started:.0f} s")


if __name__ == "__main__":
    main()
