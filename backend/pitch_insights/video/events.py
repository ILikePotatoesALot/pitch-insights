"""Events from tracked players and the ball (video path).

Simple rules, as designed (DESIGN.md, "From detections to messages"): the
nearest player within `POSSESSION_RADIUS_M` of the ball has it. A change of
possession between teammates is a `pass`, a run with the ball over 3 m is a
`carry`, and a change to an opponent is a turnover: an `interception` when the
ball travelled, otherwise a `tackle`. Shots are not attempted: at 5 frames a
second the ball is often missed in flight, and a shot's outcome can't be told
from the ball alone.

Works in SoccerTrack metres (origin at the centre spot); `to_messages` turns
the result into event-format v1 messages in each actor's attacking frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..events.schema import PITCH_LENGTH, PITCH_WIDTH, display_clock, dump, event_adapter
from .soccertrack import to_our_frame

Point = tuple[float, float]

POSSESSION_RADIUS_M = 2.0
MIN_SEGMENT_FRAMES = 2  # a ball passing a player in a single frame isn't possession
MAX_GAP_S = 3.0  # longer without anyone on the ball and the chain breaks
CARRY_MIN_M = 3.0


@dataclass(frozen=True, slots=True)
class PlayerAt:
    id: str
    team: str
    pos: Point


@dataclass(frozen=True, slots=True)
class Moment:
    t: float
    ball: Point | None
    ball_conf: float
    players: tuple[PlayerAt, ...]


@dataclass
class Segment:
    owner: str
    team: str
    t0: float
    t1: float
    ball0: Point
    ball1: Point
    pos0: Point
    pos1: Point
    confs: list[float]
    frames: int = 1


@dataclass(frozen=True, slots=True)
class RawEvent:
    t: float
    type: str
    team: str
    player: str
    pos: Point
    end: Point | None = None
    other: str | None = None  # receiver for passes
    duration: float = 0.0
    outcome: str | None = None
    confidence: float = 0.5


def owner(m: Moment) -> PlayerAt | None:
    if m.ball is None:
        return None
    best = min(m.players, key=lambda p: math.dist(p.pos, m.ball), default=None)
    if best is None or math.dist(best.pos, m.ball) > POSSESSION_RADIUS_M:
        return None
    return best


def segments(moments: list[Moment]) -> list[Segment]:
    out: list[Segment] = []
    cur: Segment | None = None
    for m in moments:
        p = owner(m)
        if p is None:
            continue
        if cur and cur.owner == p.id and m.t - cur.t1 <= MAX_GAP_S:
            cur.t1, cur.ball1, cur.pos1 = m.t, m.ball, p.pos
            cur.confs.append(m.ball_conf)
            cur.frames += 1
            continue
        if cur:
            out.append(cur)
        cur = Segment(p.id, p.team, m.t, m.t, m.ball, m.ball, p.pos, p.pos, [m.ball_conf])
    if cur:
        out.append(cur)
    return [s for s in out if s.frames >= MIN_SEGMENT_FRAMES]


def _conf(values: list[float]) -> float:
    return round(min(0.95, max(0.05, 0.9 * sum(values) / len(values))), 2)


def derive(moments: list[Moment]) -> list[RawEvent]:
    segs = segments(moments)
    events: list[RawEvent] = []
    for s in segs:
        if math.dist(s.pos0, s.pos1) >= CARRY_MIN_M:
            events.append(RawEvent(s.t0, "carry", s.team, s.owner, s.pos0, s.pos1,
                                   duration=round(s.t1 - s.t0, 2), confidence=_conf(s.confs)))
    for a, b in zip(segs, segs[1:]):
        if b.t0 - a.t1 > MAX_GAP_S:
            continue
        conf = _conf(a.confs[-2:] + b.confs[:2])
        if a.team == b.team:
            if a.owner != b.owner:
                events.append(RawEvent(a.t1, "pass", a.team, a.owner, a.ball1, b.ball0,
                                       other=b.owner, outcome="complete", confidence=conf))
        elif math.dist(a.ball1, b.ball0) >= CARRY_MIN_M:
            events.append(RawEvent(a.t1, "pass", a.team, a.owner, a.ball1, b.ball0,
                                   outcome="incomplete", confidence=conf))
            events.append(RawEvent(b.t0, "interception", b.team, b.owner, b.ball0,
                                   outcome="won", confidence=conf))
        else:
            events.append(RawEvent(b.t0, "tackle", b.team, b.owner, b.ball0,
                                   outcome="won", confidence=conf))
    return sorted(events, key=lambda e: e.t)


def _clamp(p: Point) -> Point:
    return (min(max(p[0], 0.0), PITCH_LENGTH), min(max(p[1], 0.0), PITCH_WIDTH))


def to_messages(
    events: list[RawEvent], match_id: str, period: int, attacks_plus_x: dict[str, bool], first_seq: int = 1,
) -> list[dict]:
    """Event-format v1 messages, validated, with `source: "video"`.

    Fields video can't see take neutral values: passes are `ground`,
    `open_play`, difficulty 0.5.
    """
    out = []
    for n, e in enumerate(events):
        plus = attacks_plus_x[e.team]
        x, y = _clamp(to_our_frame(*e.pos, plus))
        clock, minute = display_clock(period, e.t)
        msg: dict = {
            "schema": "1.0", "match_id": match_id, "seq": first_seq + n, "source": "video",
            "t": round(e.t, 2), "period": period, "clock": clock, "minute": minute,
            "type": e.type, "team_id": e.team, "player_id": e.player,
            "x": round(x, 1), "y": round(y, 1), "confidence": e.confidence,
        }
        if e.type in ("pass", "carry"):
            ex, ey = _clamp(to_our_frame(*e.end, plus))
            msg["end_x"], msg["end_y"] = round(ex, 1), round(ey, 1)
        if e.type == "pass":
            msg.update(receiver_id=e.other, outcome=e.outcome, length=round(math.dist(e.pos, e.end), 1),
                       height="ground", kind="open_play", difficulty=0.5)
        elif e.type == "carry":
            msg["duration"] = e.duration
        else:
            msg["outcome"] = e.outcome
        out.append(dump(event_adapter.validate_python(msg)))
    return out
