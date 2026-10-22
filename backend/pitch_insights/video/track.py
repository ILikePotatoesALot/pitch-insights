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
from statistics import median

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
    gate_m: float = 2.5  # how far a detection may be from a track's predicted position
    max_missed: int = 10  # steps a track survives without a detection (2 s at 5 fps)
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


def smoothed_speed(history: list[tuple[float, Point]], t: float, half_window: float = 0.25) -> float | None:
    """Speed in m/s at time `t`, from the positions about `half_window` s either side."""
    times = [h[0] for h in history]
    if t not in times:
        return None
    i = times.index(t)
    lo = i
    while lo > 0 and t - times[lo - 1] <= half_window + 1e-9:
        lo -= 1
    hi = i
    while hi < len(times) - 1 and times[hi + 1] - t <= half_window + 1e-9:
        hi += 1
    if hi == lo:
        return None
    return math.dist(history[hi][1], history[lo][1]) / (times[hi] - times[lo])


FAR_STRIP_Y = -27.0  # SoccerTrack y; the far touchline is at -34
SPECTATOR_MAX_SPREAD_M = 2.5
SPECTATOR_MIN_POINTS = 5


def spectator_tracks(history: dict[int, list[tuple[float, Point]]]) -> set[int]:
    """Tracks that are people on the stand behind the far touchline, not players.

    SoccerTrack positions (y towards the camera). The stand is raised, so from
    this camera their feet land on the far touchline and map onto the pitch.
    They stay in the strip by the far touchline and barely move; players there
    run. Needs a track's whole history, so it is an offline filter.
    """
    out = set()
    for tid, hist in history.items():
        pts = [p for _, p in hist]
        if len(pts) < SPECTATOR_MIN_POINTS or max(p[1] for p in pts) > FAR_STRIP_Y:
            continue
        centre = (median(p[0] for p in pts), median(p[1] for p in pts))
        if max(math.dist(p, centre) for p in pts) < SPECTATOR_MAX_SPREAD_M:
            out.add(tid)
    return out
