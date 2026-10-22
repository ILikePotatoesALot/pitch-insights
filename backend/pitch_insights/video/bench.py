"""Scoring the video path against SoccerTrack's ground truth.

Positions are compared in pitch metres, not image boxes, because SoccerTrack's
image boxes are approximate (all 43 px tall) while its pitch positions are the
annotated truth. A detection and a ground-truth player match when they are the
closest unmatched pair within `max_dist` metres (greedy, closest pairs first).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean, median

Point = tuple[float, float]


def match_points(found: list[Point], truth: list[Point], max_dist: float) -> list[tuple[int, int, float]]:
    """Pairs `(found index, truth index, distance)`, closest first, each point used once."""
    pairs = sorted(
        (math.dist(f, g), i, j)
        for i, f in enumerate(found)
        for j, g in enumerate(truth)
    )
    used_f: set[int] = set()
    used_t: set[int] = set()
    out = []
    for d, i, j in pairs:
        if d > max_dist:
            break
        if i in used_f or j in used_t:
            continue
        used_f.add(i)
        used_t.add(j)
        out.append((i, j, d))
    return out


def _percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class DetectionScore:
    """Running totals over frames."""

    max_dist: float
    found: int = 0
    truth: int = 0
    errors: list[float] = field(default_factory=list)

    def add_frame(self, found: list[Point], truth: list[Point]) -> list[tuple[int, int, float]]:
        pairs = match_points(found, truth, self.max_dist)
        self.found += len(found)
        self.truth += len(truth)
        self.errors += [d for _, _, d in pairs]
        return pairs

    def summary(self) -> dict[str, float]:
        matched = len(self.errors)
        return {
            "match_radius_m": self.max_dist,
            "recall": matched / self.truth if self.truth else float("nan"),
            "precision": matched / self.found if self.found else float("nan"),
            "position_error_mean_m": mean(self.errors) if self.errors else float("nan"),
            "position_error_median_m": median(self.errors) if self.errors else float("nan"),
            "position_error_p90_m": _percentile(self.errors, 0.9),
            "detections": self.found,
            "ground_truth": self.truth,
            "matched": matched,
        }


def event_recall(
    predicted: list[tuple[float, str]], truth: list[tuple[float, str]], window: float,
) -> dict[str, dict[str, float]]:
    """Share of true events with a predicted event of the same type within `window` seconds, by type.

    Each predicted event can account for one true event only. `"all"` gives the
    overall share and the precision (share of predicted events that matched).
    """
    by_type: dict[str, list[int]] = {}
    used: set[int] = set()
    for t, kind in sorted(truth):
        hit = 0
        best = None
        for k, (pt, pkind) in enumerate(predicted):
            if k in used or pkind != kind or abs(pt - t) > window:
                continue
            if best is None or abs(pt - t) < abs(predicted[best][0] - t):
                best = k
        if best is not None:
            used.add(best)
            hit = 1
        by_type.setdefault(kind, []).append(hit)
    out = {kind: {"truth": len(h), "found": sum(h), "recall": sum(h) / len(h)} for kind, h in sorted(by_type.items())}
    total = sum(len(h) for h in by_type.values())
    hits = sum(sum(h) for h in by_type.values())
    out["all"] = {
        "truth": total,
        "found": hits,
        "recall": hits / total if total else float("nan"),
        "predicted": len(predicted),
        "precision": len(used) / len(predicted) if predicted else float("nan"),
    }
    return out
