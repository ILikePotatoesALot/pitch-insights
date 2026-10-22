"""Image pixels to pitch metres for SoccerTrack's fixed panoramic camera.

SoccerTrack ships no camera calibration, and a single homography doesn't fit a
stitched panorama (4.2 m mean error on the ground truth). A 2-D polynomial
does: degree 5 reaches about 0.6 m on SoccerTrack's own boxes, close to the
1.05 x 0.68 m grid its positions are stored on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _terms(degree: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(degree + 1) for j in range(degree + 1 - i)]


@dataclass
class PolyMap:
    """(a, b) -> (c, d) as a polynomial of degree `degree` in normalised a and b."""

    degree: int
    centre: tuple[float, float]
    scale: tuple[float, float]
    coef: np.ndarray  # (terms, 2)

    def _features(self, pts: np.ndarray) -> np.ndarray:
        a = (pts[:, 0] - self.centre[0]) / self.scale[0]
        b = (pts[:, 1] - self.centre[1]) / self.scale[1]
        return np.stack([a**i * b**j for i, j in _terms(self.degree)], axis=1)

    def __call__(self, pts) -> np.ndarray:
        pts = np.asarray(pts, dtype=float).reshape(-1, 2)
        return self._features(pts) @ self.coef

    @classmethod
    def fit(cls, src, dst, degree: int, centre, scale) -> PolyMap:
        src = np.asarray(src, dtype=float)
        dst = np.asarray(dst, dtype=float)
        m = cls(degree, tuple(centre), tuple(scale), np.zeros((len(_terms(degree)), 2)))
        m.coef, *_ = np.linalg.lstsq(m._features(src), dst, rcond=None)
        return m

    def to_json(self) -> dict:
        return {"degree": self.degree, "centre": list(self.centre), "scale": list(self.scale),
                "coef": [[round(float(v), 9) for v in row] for row in self.coef]}

    @classmethod
    def from_json(cls, d: dict) -> PolyMap:
        return cls(d["degree"], tuple(d["centre"]), tuple(d["scale"]), np.array(d["coef"], dtype=float))


IMAGE_CENTRE, IMAGE_SCALE = (2048.0, 540.0), (2048.0, 540.0)
PITCH_CENTRE, PITCH_SCALE = (0.0, 0.0), (52.5, 34.0)


def fit_image_to_pitch(uv, xy, degree: int) -> PolyMap:
    return PolyMap.fit(uv, xy, degree, IMAGE_CENTRE, IMAGE_SCALE)


def fit_pitch_to_image(xy, uv, degree: int) -> PolyMap:
    return PolyMap.fit(xy, uv, degree, PITCH_CENTRE, PITCH_SCALE)


@dataclass
class Calibration:
    to_pitch: PolyMap
    to_image: PolyMap
    margin_m: float = 2.0

    def pitch_outline(self, step: float = 1.0) -> np.ndarray:
        """The pitch's edge plus the margin, in image pixels (for drawing and filtering)."""
        hx, hy = 52.5 + self.margin_m, 34.0 + self.margin_m
        xs = np.arange(-hx, hx + 1e-9, step)
        ys = np.arange(-hy, hy + 1e-9, step)
        edge = np.concatenate([
            np.stack([xs, np.full_like(xs, -hy)], 1),
            np.stack([np.full_like(ys, hx), ys], 1),
            np.stack([xs[::-1], np.full_like(xs, hy)], 1),
            np.stack([np.full_like(ys, -hx), ys[::-1]], 1),
        ])
        return self.to_image(edge)

    def on_pitch(self, uv) -> tuple[np.ndarray, np.ndarray]:
        """Pitch positions for image points, and which lie on the pitch (with the margin).

        Both directions must agree: the point must be inside the pitch outline in
        the image, and map inside the pitch, so the polynomial's extrapolation
        beyond the calibrated area (stands, the logo) can't fold back onto the pitch.
        """
        import cv2

        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        xy = self.to_pitch(uv)
        outline = self.pitch_outline().astype(np.float32)
        inside_img = np.array([cv2.pointPolygonTest(outline, (float(u), float(v)), False) >= 0 for u, v in uv], dtype=bool)
        inside_pitch = (np.abs(xy[:, 0]) <= 52.5 + self.margin_m) & (np.abs(xy[:, 1]) <= 34.0 + self.margin_m)
        return xy, inside_img & inside_pitch

    def save(self, path: Path, extra: dict | None = None) -> None:
        d = {"to_pitch": self.to_pitch.to_json(), "to_image": self.to_image.to_json(), "margin_m": self.margin_m}
        d.update(extra or {})
        path.write_text(json.dumps(d, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Calibration:
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(PolyMap.from_json(d["to_pitch"]), PolyMap.from_json(d["to_image"]), d.get("margin_m", 2.0))
