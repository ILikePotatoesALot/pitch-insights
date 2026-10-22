"""A small ByteTrack-style tracker that works in pitch metres.

supervision 0.31 no longer ships ByteTrack (it moved to Roboflow's separate
`trackers` package), so this follows ByteTrack's idea without the package:
match confident detections to tracks first, then give the leftover tracks a
second chance with the low-confidence detections, which are often players
half-hidden by someone else. Matching is by distance on the pitch after a
constant-velocity prediction, which suits 5 frames a second better than box
overlap in the image (a running player can move a whole box width per frame).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass
class Track:
    id: int
    pos: Point
    t: float
    vel: Point = (0.0, 0.0)
    hits: int = 1
    missed: int = 0
    history: list[tuple[float, Point]] = field(default_factory=list)

    def predict(self, t: float) -> Point:
        dt = t - self.t
        return (self.pos[0] + self.vel[0] * dt, self.pos[1] + self.vel[1] * dt)


@dataclass
class PitchTracker:
    high: float = 0.5  # detections at or above this start tracks and match first
    # How far a detection may be from a track's predicted position. Closest pairs
    # match first, so a wide gate mostly helps a track survive a missed frame or a
    # bad prediction; 2.5 m kept a player's ID for 69% of their frames, 6 m for 80%
    # (chosen on the 38-minute clip, so that figure is optimistic).
    gate_m: float = 6.0
    max_missed: int = 25  # steps a track survives without a detection (5 s at 5 fps)
    max_speed: float = 10.0  # m/s; velocity estimates are capped here
    tracks: list[Track] = field(default_factory=list)
    next_id: int = 1

    def update(self, t: float, points: list[Point], scores: list[float]) -> list[int | None]:
        """Assign a track ID to each detection at time `t` (None for an unmatched low-confidence one)."""
        ids: list[int | None] = [None] * len(points)
        free = list(range(len(self.tracks)))
        for stage in ("high", "low"):
            idx = [i for i, s in enumerate(scores) if ids[i] is None and ((s >= self.high) == (stage == "high"))]
            if not idx or not free:
                continue
            predicted = [self.tracks[k].predict(t) for k in free]
            # A track that has been missing may have moved further, so its gate widens.
            gate = [self.gate_m + 0.5 * self.tracks[k].missed for k in free]
            pairs = sorted(
                (d, a, b)
                for a, i in enumerate(idx)
                for b, p in enumerate(predicted)
                if (d := math.dist(points[i], p)) <= gate[b]
            )
            used_a: set[int] = set()
            taken: set[int] = set()
            for _, a, b in pairs:
                if a in used_a or b in taken:
                    continue
                self._hit(self.tracks[free[b]], t, points[idx[a]])
                ids[idx[a]] = self.tracks[free[b]].id
                used_a.add(a)
                taken.add(b)
            free = [k for n, k in enumerate(free) if n not in taken]
        for k in free:
            self.tracks[k].missed += 1
        self.tracks = [tr for tr in self.tracks if tr.missed <= self.max_missed]
        for i, s in enumerate(scores):
            if ids[i] is None and s >= self.high:
                tr = Track(self.next_id, points[i], t, history=[(t, points[i])])
                self.next_id += 1
                self.tracks.append(tr)
                ids[i] = tr.id
        return ids

    def _hit(self, tr: Track, t: float, p: Point) -> None:
        dt = t - tr.t
        if dt > 0:
            vx = (p[0] - tr.pos[0]) / dt
            vy = (p[1] - tr.pos[1]) / dt
            vx, vy = 0.5 * tr.vel[0] + 0.5 * vx, 0.5 * tr.vel[1] + 0.5 * vy
            speed = math.hypot(vx, vy)
            if speed > self.max_speed:
                vx, vy = vx * self.max_speed / speed, vy * self.max_speed / speed
            tr.vel = (vx, vy)
        tr.pos, tr.t = p, t
        tr.hits += 1
        tr.missed = 0
        tr.history.append((t, p))


def smoothed_speeds(history: list[tuple[float, Point]], half_window: float = 0.25) -> dict[float, float | None]:
    """Speed in m/s at each time in a track's history (in time order), from the
    positions up to `half_window` s either side; None where there is no neighbour."""
    times = [h[0] for h in history]
    out: dict[float, float | None] = {}
    lo = hi = 0
    for i, t in enumerate(times):
        while t - times[lo] > half_window + 1e-9:
            lo += 1
        hi = max(hi, i)
        while hi < len(times) - 1 and times[hi + 1] - t <= half_window + 1e-9:
            hi += 1
        out[t] = None if hi == lo else math.dist(history[hi][1], history[lo][1]) / (times[hi] - times[lo])
    return out


FAR_STRIP_Y = -24.0  # SoccerTrack y; the far touchline is at -34
BEHIND_GOAL_X = 52.0  # the goal lines are at +-52.5
STATIC_CELL_M = 2.0
STATIC_MIN_SHARE = 0.15  # of all frames
STATIC_SLICES = 5  # the clip cut into this many equal parts in time
STATIC_MIN_SLICES = 3  # a static spot is occupied in at least this many of them

Cell = tuple[int, int, int]  # grid (0, or 1 for the one offset by half a cell), x, y


def _cells(p: Point) -> tuple[Cell, Cell]:
    """The point's cell in two grids offset by half a cell, so a point on one
    grid's cell edge sits in the middle of a cell of the other."""
    h = STATIC_CELL_M / 2
    return (
        (0, math.floor(p[0] / STATIC_CELL_M), math.floor(p[1] / STATIC_CELL_M)),
        (1, math.floor((p[0] + h) / STATIC_CELL_M), math.floor((p[1] + h) / STATIC_CELL_M)),
    )


def _off_field_zone(p: Point) -> bool:
    return p[1] <= FAR_STRIP_Y or abs(p[0]) >= BEHIND_GOAL_X


def static_spots(frames: list[list[Point]], anywhere: bool = False, min_slices: int = STATIC_MIN_SLICES) -> set[Cell]:
    """Grid cells where someone stands still through the clip, off the field of play.

    SoccerTrack positions (y towards the camera). The stand behind the far
    touchline is raised, so from this camera spectators' feet land on the far
    touchline and map onto the pitch; others stand just behind a goal line.
    Only those zones are checked: a keeper standing still on the pitch is a
    player. With `anywhere` (for balls: spare balls lie around the pitch) the
    whole pitch is checked.

    A cell is static when it is occupied in at least `STATIC_MIN_SHARE` of the
    frames *and* in at least `min_slices` of `STATIC_SLICES` parts of the clip,
    so a player who stays put for a while isn't mistaken for a spectator. Balls
    pass `min_slices=1`: a spare ball is often seen only while it isn't hidden,
    and dropping the match ball during a long stoppage costs nothing. A cell counts once per frame,
    however many are in it. Needs the whole clip, so it is an offline filter.
    """
    seen: dict[Cell, int] = {}
    slices: dict[Cell, set[int]] = {}
    n = len(frames)
    for i, pts in enumerate(frames):
        part = i * STATIC_SLICES // n
        for c in {c for p in pts if anywhere or _off_field_zone(p) for c in _cells(p)}:
            seen[c] = seen.get(c, 0) + 1
            slices.setdefault(c, set()).add(part)
    return {c for c, k in seen.items() if k >= STATIC_MIN_SHARE * n and len(slices[c]) >= min_slices}


def at_static_spot(p: Point, spots: set[Cell], anywhere: bool = False) -> bool:
    return (anywhere or _off_field_zone(p)) and any(c in spots for c in _cells(p))
