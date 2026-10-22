"""SoccerTrack's MOT boxes, and what fine-tuning a detector needs from them.

`mot/<match>.txt` is the curated bounding-box subset of the MMSports 2025 challenge: the first four
minutes of the half, 22 boxes a frame (players and goalkeepers; no referees, no ball), in the video's
own pixel space. Unlike the GSR image boxes (every one 43 px tall, 10-40 px off the player) they are
tight: the box height follows the row, as our own detector's does. MOT frame k (0-based) is video
frame k + 1 (1-based), checked by matching feet positions against the GSR frames.

Pure Python, so the logic is tested without video or a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .tiles import Box, iou

FRAME_OFFSET = 1  # MOT frame k is video frame k + 1


def load_mot(path: str | Path) -> dict[int, list[Box]]:
    """Boxes (x1, y1, x2, y2) by 1-based video frame."""
    out: dict[int, list[Box]] = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            cols = line.split(",")
            try:
                frame, x, y, w, h = int(float(cols[0])), *(float(c) for c in cols[2:6])
            except (ValueError, IndexError):
                raise ValueError(f"{path}, line {n}: expected 'frame,id,x,y,w,h,...', got {line.strip()[:60]!r}") from None
            out.setdefault(frame + FRAME_OFFSET, []).append((x, y, x + w, y + h))
    return out


@dataclass(frozen=True)
class TimeSplit:
    """Train, valid and test as separate stretches of the clip, with gaps between them so that
    neighbouring frames (which look alike) never sit in two splits. Frames are 1-based video frames."""

    train: range
    valid: range
    test: range
    gap: int = 200  # frames (8 s) between one split's last frame and the next one's first

    def __post_init__(self) -> None:
        ordered = [self.train, self.valid, self.test]
        if not all(len(r) for r in ordered):
            raise ValueError("a split is empty")
        for a, b in zip(ordered, ordered[1:]):
            if b.start - a[-1] < self.gap:
                raise ValueError(f"splits overlap, are out of order, or are less than {self.gap} frames apart")

    def as_dict(self) -> dict[str, range]:
        return {"train": self.train, "valid": self.valid, "test": self.test}


# Frames 1-5,976 are in the file. A gap of 200 frames (8 s) between splits.
DEFAULT_SPLIT = TimeSplit(
    train=range(1, 3601, 8),  # 0:00 - 2:24, every 8th frame: 450 frames (the last is 3593)
    valid=range(3801, 4801, 25),  # 2:32 - 3:12: 40 frames
    test=range(5001, 5977, 25),  # 3:20 - 3:59: 40 frames
)


def clip_to_tile(box: Box, tile: tuple[int, int, int, int], min_visible: float = 0.5) -> Box | None:
    """The box in tile coordinates, clipped to the tile, or None if less than `min_visible` of it is inside.

    A person cut by a tile's edge is kept when at least half is visible (the overlap between tiles
    shows them whole in the neighbour, and the merge step joins the pieces); a smaller sliver is
    dropped from the labels, and the crop still contains it as unlabelled background."""
    tx1, ty1, tx2, ty2 = tile
    x1, y1, x2, y2 = box
    cx1, cy1, cx2, cy2 = max(x1, tx1), max(y1, ty1), min(x2, tx2), min(y2, ty2)
    if cx2 <= cx1 or cy2 <= cy1:
        return None
    area = (x2 - x1) * (y2 - y1)
    if area <= 0 or (cx2 - cx1) * (cy2 - cy1) / area < min_visible:
        return None
    return (cx1 - tx1, cy1 - ty1, cx2 - tx1, cy2 - ty1)


class CocoBuilder:
    """Collects images and boxes for one split in COCO format (one class, `player`)."""

    CATEGORY = {"id": 1, "name": "player"}

    def __init__(self) -> None:
        self.images: list[dict] = []
        self.annotations: list[dict] = []

    def add_image(self, file_name: str, width: int, height: int, boxes: list[Box]) -> int:
        image_id = len(self.images) + 1
        self.images.append({"id": image_id, "file_name": file_name, "width": width, "height": height})
        for x1, y1, x2, y2 in boxes:
            w, h = x2 - x1, y2 - y1
            self.annotations.append({
                "id": len(self.annotations) + 1, "image_id": image_id, "category_id": self.CATEGORY["id"],
                "bbox": [round(x1, 2), round(y1, 2), round(w, 2), round(h, 2)], "area": round(w * h, 2), "iscrowd": 0,
            })
        return image_id

    def to_dict(self) -> dict:
        return {"images": self.images, "annotations": self.annotations, "categories": [self.CATEGORY]}


@dataclass
class BoxScore:
    """True positives, false positives and misses at one IoU threshold, summed over images."""

    iou: float = 0.5
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add_image(self, predicted: list[tuple[Box, float]], truth: list[Box]) -> None:
        """Greedy matching, highest score first, each true box used once."""
        used: set[int] = set()
        for box, _ in sorted(predicted, key=lambda p: p[1], reverse=True):
            best, best_iou = None, self.iou
            for j, t in enumerate(truth):
                if j in used:
                    continue
                v = iou(box, t)
                if v >= best_iou:
                    best, best_iou = j, v
            if best is None:
                self.fp += 1
            else:
                used.add(best)
                self.tp += 1
        self.fn += len(truth) - len(used)

    def summary(self) -> dict[str, float]:
        found = self.tp + self.fp
        truth = self.tp + self.fn
        return {
            "iou": self.iou, "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": self.tp / found if found else float("nan"),
            "recall": self.tp / truth if truth else float("nan"),
        }
