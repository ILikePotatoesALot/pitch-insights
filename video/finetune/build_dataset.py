"""Cut SoccerTrack's MOT boxes into a tiled COCO dataset for fine-tuning RF-DETR.

The MOT file holds tight boxes for the first four minutes of the half (22 players and goalkeepers a
frame). Each chosen frame is cut into the same 5 x 2 tiles the detector uses at run time, and each
tile is saved with the boxes that fall in it (clipped, kept when at least half is visible). People
the file doesn't box, such as spectators, referees and staff, are background: that is what teaches
the model to ignore them.

Splits are stretches of the clip with gaps between them (`DEFAULT_SPLIT` in
`pitch_insights/video/mot.py`), so neighbouring frames never sit in two splits. The benchmark clip
(38:00-39:40) is nowhere near them and is never used for training.

    video\\.venv\\Scripts\\python video\\finetune\\build_dataset.py            # about 4,700 tiles
    video\\.venv\\Scripts\\python video\\finetune\\build_dataset.py --limit 3  # a few frames, to check
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import clip  # noqa: E402
from detector import tiles_for  # noqa: E402
from framesource import read_frames  # noqa: E402
from pitch_insights.video.mot import DEFAULT_SPLIT, CocoBuilder, clip_to_tile, load_mot  # noqa: E402

MOT = clip.SOURCE / "hf" / "mot" / f"{clip.MATCH}.txt"
DATASET = clip.ROOT / "data" / "finetune" / clip.MATCH
JPEG_QUALITY = 92
EMPTY_TILE_KEEP = 0.5  # share of train tiles with no player kept, as background examples


def build(out: Path, limit: int | None, seed: int = 7) -> dict[str, dict[str, int]]:
    boxes = load_mot(MOT)
    rng = random.Random(seed)
    counts: dict[str, dict[str, int]] = {}
    for split, frames in DEFAULT_SPLIT.as_dict().items():
        frames = [f for f in frames if f in boxes][:limit]
        folder = out / split  # RF-DETR's Roboflow layout: train, valid, test
        folder.mkdir(parents=True, exist_ok=True)
        coco = CocoBuilder()
        for frame, bgr in read_frames(clip.VIDEO, frames):
            height, width = bgr.shape[:2]
            for n, tile in enumerate(tiles_for(width, height)):
                tile_boxes = [b for b in (clip_to_tile(b, tile) for b in boxes[frame]) if b]
                if not tile_boxes and split == "train" and rng.random() > EMPTY_TILE_KEEP:
                    continue
                x1, y1, x2, y2 = tile
                name = f"{frame:06d}_{n}.jpg"
                cv2.imwrite(str(folder / name), bgr[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                coco.add_image(name, x2 - x1, y2 - y1, tile_boxes)
        (folder / "_annotations.coco.json").write_text(json.dumps(coco.to_dict()), encoding="utf-8")
        counts[split] = {"frames": len(frames), "tiles": len(coco.images), "boxes": len(coco.annotations)}
        print(f"{split}: {counts[split]}", flush=True)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DATASET)
    ap.add_argument("--limit", type=int, help="frames per split, for a quick check")
    ap.add_argument("--force", action="store_true", help="replace an existing dataset folder")
    args = ap.parse_args()
    if not MOT.exists():
        raise SystemExit(f"{MOT} is missing: run video/finetune/fetch_data.py first")
    if args.out.exists():
        if not args.force:
            raise SystemExit(f"{args.out} exists: pass --force to rebuild it")
        if not (args.out / "summary.json").exists():  # written at the end of every build
            raise SystemExit(f"{args.out} wasn't made by this script (no summary.json): won't delete it")
        shutil.rmtree(args.out)
    counts = build(args.out, args.limit)
    (args.out / "summary.json").write_text(json.dumps(counts, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
