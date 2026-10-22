"""Cutting a wide frame into overlapping tiles, and merging detections across tiles.

Players in SoccerTrack's 4096 x 1080 panorama are only 20-60 px tall, so the
detector sees overlapping tiles instead of the whole frame. A player near a tile
edge is then found twice, once whole and once cut off, so merging uses both IoU
and how much of the smaller box lies inside the bigger one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in frame pixels


@dataclass(frozen=True, slots=True)
class Detection:
    box: Box
    score: float
    class_id: int


def make_tiles(
    width: int, height: int, cols: int, rows: int, overlap: int,
    top: int = 0, bottom: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """Tiles covering `[0, width) x [top, bottom)`, each overlapping its neighbours by `overlap` px."""
    bottom = height if bottom is None else bottom
    if cols < 1 or rows < 1:
        raise ValueError("need at least one tile")
    if not 0 <= top < bottom <= height:
        raise ValueError("bad band")
    span_w = width
    span_h = bottom - top
    tile_w = -(-(span_w + (cols - 1) * overlap) // cols)
    tile_h = -(-(span_h + (rows - 1) * overlap) // rows)
    tiles = []
    for r in range(rows):
        y1 = top + r * (tile_h - overlap) if rows > 1 else top
        y1 = min(y1, bottom - tile_h)
        for c in range(cols):
            x1 = c * (tile_w - overlap) if cols > 1 else 0
            x1 = min(x1, width - tile_w)
            tiles.append((x1, y1, x1 + tile_w, y1 + tile_h))
    return tiles


def shift(dets: list[Detection], dx: float, dy: float) -> list[Detection]:
    """Tile coordinates to frame coordinates."""
    return [replace(d, box=(d.box[0] + dx, d.box[1] + dy, d.box[2] + dx, d.box[3] + dy)) for d in dets]


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a: Box, b: Box) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a: Box, b: Box) -> float:
    i = _inter(a, b)
    u = _area(a) + _area(b) - i
    return i / u if u > 0 else 0.0


def overlap_of_smaller(a: Box, b: Box) -> float:
    """Share of the smaller box inside the other (1.0 when one contains the other)."""
    small = min(_area(a), _area(b))
    return _inter(a, b) / small if small > 0 else 0.0


def merge(dets: list[Detection], iou_threshold: float = 0.5, contain_threshold: float = 0.7) -> list[Detection]:
    """Non-maximum suppression across tiles, per class.

    Keeps the highest-scoring box of each group. When one box mostly lies
    inside the other (a player cut off at one tile's edge and whole in the
    next), the kept box takes the union, so the whole player survives even if
    the cut-off box scored higher. Containment is checked before the plain
    IoU duplicate test: a crop that is exactly half of the whole box has an IoU
    of 0.5 and would otherwise be kept alone, with the feet cut off.
    """
    kept: list[Detection] = []
    for d in sorted(dets, key=lambda d: d.score, reverse=True):
        for i, k in enumerate(kept):
            if k.class_id != d.class_id:
                continue
            if overlap_of_smaller(k.box, d.box) >= contain_threshold:
                kb, db = k.box, d.box
                kept[i] = replace(k, box=(min(kb[0], db[0]), min(kb[1], db[1]), max(kb[2], db[2]), max(kb[3], db[3])))
                break
            if iou(k.box, d.box) >= iou_threshold:
                break
        else:
            kept.append(d)
    return kept
