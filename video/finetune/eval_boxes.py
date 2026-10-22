"""Box-level check of the detector on the held-out test frames: pre-trained against fine-tuned.

The test frames are 40 frames from 3:20 to 3:59 of the half, from the MOT file's own boxes and never
used for training or for choosing the checkpoint. Predictions come through the same tiled detection
and merging as the real pipeline. A prediction counts when it overlaps an unused true box with IoU of
0.5 (and, separately, 0.75, which also needs the box to be tight). Because the file boxes only
players and goalkeepers, referees and staff the model finds count as false positives for BOTH
models, so read the numbers as a comparison, not as absolute precision.

"On pitch" drops detections whose feet fall outside the pitch outline, as the pipeline does.

    video\\.venv\\Scripts\\python video\\finetune\\eval_boxes.py --weights path\\to\\checkpoint.pth
    video\\.venv\\Scripts\\python video\\finetune\\eval_boxes.py --limit 2     # pre-trained only, quick
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clip  # noqa: E402
from calibration import Calibration  # noqa: E402
from detector import PERSON, TiledDetector  # noqa: E402
from framesource import read_frames  # noqa: E402
from pitch_insights.video.mot import DEFAULT_SPLIT, BoxScore, load_mot  # noqa: E402

MOT = clip.SOURCE / "hf" / "mot" / f"{clip.MATCH}.txt"
OUT = clip.SAMPLES / f"{clip.MATCH}-boxes.eval.json"
IOUS = (0.5, 0.75)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", help="fine-tuned checkpoint to compare with the pre-trained model")
    ap.add_argument("--limit", type=int, help="test frames to use (default: all 40)")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    boxes = load_mot(MOT)
    frames = [f for f in DEFAULT_SPLIT.test if f in boxes][:args.limit]
    detectors = {"pre-trained": TiledDetector()}
    if args.weights:
        detectors["fine-tuned"] = TiledDetector(args.weights)
    cal = Calibration.load(clip.BASELINE_CALIBRATION) if clip.BASELINE_CALIBRATION.exists() else None
    scores = {(name, view, i): BoxScore(iou=i) for name in detectors for view in ("all", "on pitch") for i in IOUS}

    for frame, bgr in read_frames(clip.VIDEO, frames):
        for name, detector in detectors.items():
            found = [d for d in detector.detect(bgr) if d.class_id == PERSON and d.score >= clip.PERSON_MIN_SCORE]
            on_pitch = found
            if cal and found:
                _, keep = cal.on_pitch([((d.box[0] + d.box[2]) / 2, d.box[3]) for d in found])
                on_pitch = [d for d, k in zip(found, keep) if k]
            for i in IOUS:
                scores[(name, "all", i)].add_image([(d.box, d.score) for d in found], boxes[frame])
                scores[(name, "on pitch", i)].add_image([(d.box, d.score) for d in on_pitch], boxes[frame])
        print(f"frame {frame} done", flush=True)

    result = {"frames": len(frames), "min_score": clip.PERSON_MIN_SCORE, "results": {}}
    print(f"\n{len(frames)} test frames, {sum(len(boxes[f]) for f in frames)} true boxes")
    print(f"{'detector':12} {'view':9} {'IoU':>5} {'precision':>10} {'recall':>8}")
    for (name, view, i), s in scores.items():
        out = s.summary()
        result["results"][f"{name} | {view} | IoU {i}"] = out
        print(f"{name:12} {view:9} {i:5.2f} {out['precision']:10.3f} {out['recall']:8.3f}")
    if not args.no_save and not args.limit:
        OUT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
