"""Tiled RF-DETR (small) for the 4096 x 1080 panorama.

The whole frame at the model's 512 px input finds only a handful of players, so
the band of the image that holds the pitch (rows 90-790) is cut into 5 x 2
overlapping tiles, each tile is detected separately, and boxes are merged
across tiles. About 7 s a frame on a laptop CPU, a fraction of that on a GPU.

By default the model is the COCO-pre-trained one as released. With `weights`, people come from
a fine-tuned model (one class, `player`) and the ball still comes from the pre-trained one,
because the fine-tuning data (SoccerTrack's MOT boxes) has no ball.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import cv2
import numpy as np

import clip  # noqa: F401  (puts backend/ on sys.path)
from pitch_insights.video.tiles import Detection, make_tiles, merge, shift

PERSON = 1  # COCO ids, as in rfdetr.assets.coco_classes
BALL = 37
KEEP = {PERSON, BALL}
TILE_COLS, TILE_ROWS, TILE_OVERLAP = 5, 2, 96
BAND_TOP, BAND_BOTTOM = 90, 790  # the pitch's rows in this fixed camera's frame
THRESHOLD = 0.2  # low, to keep the ball; players are filtered at 0.3 later


def tiles_for(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """The tile layout, shared by detection and by the fine-tuning data so the model trains on what it sees."""
    return make_tiles(width, height, TILE_COLS, TILE_ROWS, TILE_OVERLAP, BAND_TOP, min(BAND_BOTTOM, height))


class TiledDetector:
    def __init__(self, weights: str | None = None) -> None:
        import truststore

        truststore.inject_into_ssl()  # the network inspects HTTPS
        warnings.filterwarnings("ignore")
        from rfdetr import RFDETRSmall

        self.weights = weights
        self.model = RFDETRSmall()  # COCO weights: people, and always the ball
        self.people = RFDETRSmall(pretrain_weights=weights) if weights else None

    def describe(self) -> dict:
        """What made these detections: stored beside them and copied into the benchmark."""
        import torch

        device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        if self.weights:
            return {"model": "RF-DETR small fine-tuned (people) + COCO pre-trained (ball)",
                    "weights": Path(self.weights).name, "fine_tuned": True, "device": device}
        return {"model": "RF-DETR small (rfdetr 1.11.2), COCO weights as released, no fine-tuning",
                "weights": None, "fine_tuned": False, "device": device}

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        h, w = bgr.shape[:2]
        tiles = tiles_for(w, h)
        rgb = bgr[:, :, ::-1]
        crops = [np.ascontiguousarray(rgb[y1:y2, x1:x2]) for x1, y1, x2, y2 in tiles]
        results = self.model.predict(crops, threshold=THRESHOLD)
        people = self.people.predict(crops, threshold=THRESHOLD) if self.people else None
        keep = KEEP if people is None else {BALL}  # fine-tuned people replace the COCO person class
        dets: list[Detection] = []
        for i, (x1, y1, _, _) in enumerate(tiles):
            r = results[i]
            found = [
                Detection(tuple(float(v) for v in b), float(s), int(c))
                for b, s, c in zip(r.xyxy, r.confidence, r.class_id)
                if int(c) in keep
            ]
            if people is not None:
                found += [Detection(tuple(float(v) for v in b), float(s), PERSON)
                          for b, s in zip(people[i].xyxy, people[i].confidence)]
            dets += shift(found, x1, y1)
        return merge(dets)


def shirt_colour(bgr: np.ndarray, box: tuple[float, float, float, float]) -> list[float] | None:
    """Mean Lab colour of the shirt: the upper body, centre columns, grass masked out."""
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    sx1, sx2 = int(x1 + 0.25 * bw), int(x2 - 0.25 * bw)
    sy1, sy2 = int(y1 + 0.15 * bh), int(y1 + 0.5 * bh)
    crop = bgr[max(sy1, 0):max(sy2, 0), max(sx1, 0):max(sx2, 0)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    grass = (hsv[:, 0] >= 35) & (hsv[:, 0] <= 85) & (hsv[:, 1] >= 60)
    keep = lab[~grass]
    if len(keep) < 4:
        return None
    return [round(float(v), 1) for v in keep.mean(axis=0)]
