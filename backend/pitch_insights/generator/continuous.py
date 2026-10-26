"""Experimental continuous simulation. Positions are the source of events.

A short, seeded first-half exhibition, not a calibrated 90-minute match model.
All movement uses one absolute pitch; output uses each team's attacking frame.
The existing event engine supplies squads, metadata and event validation only.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass

from pitch_insights.generator.engine import MatchEngine, PState, flip
from pitch_insights.generator.players import load_clubs
from pitch_insights.generator.xg import expected_goals

NAME = "continuous-prototype"
DURATION = 360
DT = 0.2


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def lane_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    k = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / max(0.01, dx * dx + dy * dy)))
    return distance(p, (a[0] + k * dx, a[1] + k * dy))


@dataclass
class Runner:
    player: PState
    side: int
    xy: tuple[float, float]
    velocity: tuple[float, float] = (0.0, 0.0)


class ContinuousMatch:
    def __init__(self, seed=42):
        clubs = load_clubs()
        self.engine = MatchEngine(seed, clubs["POT"], clubs["CAR"])
        self.engine.match_id = f"SIM-{seed}"
        self.rng = self.engine.rng
        self.runners = {}
        for side, team in enumerate(self.engine.teams):
            for player in team.on_pitch:
                x, y = player.anchor
                # Begin in each team's own half, then expand with possession.
                xy = (min(48, x * 0.65), y)
                self.runners[player.id] = Runner(player, side, flip(*xy) if side else xy)
        self.ball = (52.5, 34.0)
        self.owner = min((r for r in self.runners.values() if r.side == 0), key=lambda r: distance(r.xy, self.ball))
        self.owner.xy = self.ball
        self.side = 0
        self.flight = None
        self.restart_until = 0.0
        self.restart_side = 0
        self.restart_kind = None
        self.restart_point = (52.5, 34.0)
        self.restart_taker = None
        self.held_until = 0.0
        self.pending_pass_kind = "open_play"
        self.next_decision = 1.6
        self.carry_start = (0.0, self.ball)
        self.frames = []

    def own(self, xy, side):
        return flip(*xy) if side else xy

    def emit(self, event_type, runner=None, xy=None, **fields):
        team = self.engine.teams[runner.side] if runner else None
        point = self.own(xy or runner.xy, runner.side) if runner else (None, None)
        self.engine.emit(event_type, team, runner.player if runner else None, *point, **fields)

    def take_ball(self, runner):
        self.held_until = 0
        if runner.side != self.side:
            self.engine.possession_id += 1
        self.side = runner.side
        self.owner = runner
        self.flight = None
        self.next_decision = self.engine.t + self.rng.uniform(1.6, 2.8)
        self.carry_start = (self.engine.t, runner.xy)

    def begin_restart(self, kind, side):
        self.restart_kind, self.restart_side = kind, side
        self.restart_until = self.engine.t + (12 if kind == "kickoff" else 4)
        self.restart_point = (52.5, 34.0) if kind == "kickoff" else self.own((5, 34), side)
        candidates = [r for r in self.runners.values() if r.side == side
                      and (r.player.role == "GK") == (kind == "goal_kick")]
        self.restart_taker = min(candidates, key=lambda r: distance(r.xy, self.restart_point))
        self.owner = self.flight = None

    def restart_ready(self):
        if self.engine.t < self.restart_until or distance(self.ball, self.restart_point) > 0.05:
            return False
        if distance(self.restart_taker.xy, self.restart_point) > 0.5:
            return False
        for r in self.runners.values():
            x, y = self.own(r.xy, r.side)
            if self.restart_kind == "kickoff":
                if r is not self.restart_taker and x > 52.55:
                    return False
                if r.side != self.restart_side and distance(r.xy, self.ball) < 9.15:
                    return False
            elif r.side != self.restart_side:
                rx, ry = self.own(r.xy, self.restart_side)
                if rx < 16.5 and 13.84 < ry < 54.16:
                    return False
        return True

    def targets(self):
        targets = {}
        for side, team in enumerate(self.engine.teams):
            bx, by = self.own(self.ball, side)
            members = [r for r in self.runners.values() if r.side == side]
            pressers = sorted((r for r in members if r.player.role != "GK"), key=lambda r: distance(r.xy, self.ball))[:2]
            for r in members:
                ax, ay = r.player.anchor
                if self.restart_kind == "kickoff":
                    target = (min(48 if side == self.restart_side else 43, ax * 0.65), ay)
                elif r.player.role == "GK":
                    target = (5 + max(0, bx - 40) * 0.10, 34 + (by - 34) * 0.2)
                elif side == self.side:
                    target = (ax + (bx - 52.5) * 0.52 + 7,
                              34 + (ay - 34) * 1.05 + (by - 34) * 0.24)
                    # Off-ball runs change with time and role, without resampling positions.
                    phase = self.engine.t * 0.32 + r.player.pdef.number
                    target = (target[0] + 4 * math.sin(phase), target[1] + 3 * math.cos(phase * 0.7))
                else:
                    target = (ax + (bx - 52.5) * 0.5 - 7 + team.style["line"],
                              34 + (ay - 34) * 0.72 + (by - 34) * 0.4)
                    if r in pressers:
                        target = (bx - (1.0 if r is pressers[0] else 4), by + (0 if r is pressers[0] else 3))
                    elif bx < 60:
                        threats = [p for p in self.runners.values() if p.side != side and p.player.role != "GK"]
                        mark = min(threats, key=lambda p: distance(r.xy, p.xy))
                        mx, my = self.own(mark.xy, side)
                        target = (target[0] * 0.6 + (mx - 2) * 0.4, target[1] * 0.6 + my * 0.4)
                if r is self.owner and not self.restart_until:
                    if r.player.role == "GK" or self.pending_pass_kind != "open_play":
                        target = self.own(r.xy, side)
                    else:
                        opponents = [p for p in self.runners.values() if p.side != side]
                        nearest = min(opponents, key=lambda p: distance(r.xy, p.xy))
                        pressure = distance(r.xy, nearest.xy)
                        _, py = self.own(nearest.xy, side)
                        target = (min(99, bx + (4 if pressure < 5 else 9)),
                                  by + ((-5 if py > by else 5) if pressure < 5 else (34 - by) * 0.2))
                target = (max(2, min(103, target[0])), max(2, min(66, target[1])))
                targets[r.player.id] = self.own(target, side)
                if self.restart_kind == "goal_kick" and side != self.restart_side:
                    rx, ry = self.own(targets[r.player.id], self.restart_side)
                    if rx < 18 and 12 < ry < 56:
                        targets[r.player.id] = self.own((18, ry), self.restart_side)
        if self.flight and self.flight["kind"] == "pass":
            targets[self.flight["receiver"].player.id] = self.flight["end"]
        if self.flight and self.flight["kind"] == "shot" and self.flight["outcome"] == "saved":
            targets[self.flight["keeper"].player.id] = self.flight["end"]
        if self.restart_kind:
            targets[self.restart_taker.player.id] = self.restart_point
        return targets

    def move_players(self):
        targets = self.targets()
        before = {pid: r.xy for pid, r in self.runners.items()}
        for pid, r in self.runners.items():
            tx, ty = targets[pid]
            dx, dy = tx - r.xy[0], ty - r.xy[1]
            gap = math.hypot(dx, dy)
            vmax = 4.8 + r.player.pdef.attributes["pace"] * 0.035
            if r is self.owner:
                vmax *= 0.72
            speed = min(vmax, gap * 1.8)
            desired = (dx / max(gap, 0.001) * speed, dy / max(gap, 0.001) * speed)
            # Teammates preserve personal space; opponents can still get close enough to tackle.
            sx = sy = 0.0
            for other_id, other in self.runners.items():
                if other_id == pid:
                    continue
                ox, oy = before[other_id]
                apart = distance(r.xy, (ox, oy))
                radius = 2.2 if other.side == r.side else 0.7
                if 0.01 < apart < radius:
                    push = (radius - apart) * 2.5 / apart
                    sx += (r.xy[0] - ox) * push
                    sy += (r.xy[1] - oy) * push
            desired = (desired[0] + sx, desired[1] + sy)
            limit = min(1, vmax / max(0.001, math.hypot(*desired)))
            desired = (desired[0] * limit, desired[1] * limit)
            dv = (desired[0] - r.velocity[0], desired[1] - r.velocity[1])
            scale = min(1, 4.5 * DT / max(0.001, math.hypot(*dv)))
            r.velocity = (r.velocity[0] + dv[0] * scale, r.velocity[1] + dv[1] * scale)
            r.xy = (max(0, min(105, r.xy[0] + r.velocity[0] * DT)), max(0, min(68, r.xy[1] + r.velocity[1] * DT)))

    def carry_event(self):
        t, xy = self.carry_start
        if self.owner and distance(xy, self.owner.xy) > 3:
            ex, ey = self.own(self.owner.xy, self.owner.side)
            self.emit("carry", self.owner, xy, end_x=ex, end_y=ey, duration=round(self.engine.t - t, 1))
        if self.owner:
            self.carry_start = (self.engine.t, self.owner.xy)

    def decide(self):
        r = self.owner
        enemies = [p for p in self.runners.values() if p.side != r.side]
        closest = min(enemies, key=lambda p: distance(p.xy, self.ball))
        pressure = distance(closest.xy, self.ball)
        if pressure < 4:
            self.emit("pressure", closest, target_player_id=r.player.id)
        x, y = self.own(r.xy, r.side)
        self.carry_event()
        if r.player.role != "GK" and x > 82 and abs(y - 34) < 22 and self.rng.random() < 0.16 + (x - 82) / 55:
            xg = expected_goals(x, y, under_pressure=pressure < 4)
            goal = self.rng.random() < min(0.75, xg * r.player.pdef.attributes["shooting"] / 65)
            keeper = next(p for p in enemies if p.player.role == "GK")
            outcome = "goal" if goal else self.rng.choice(["saved", "off_target"])
            end = (keeper.xy[0], keeper.xy[1] + self.rng.uniform(-0.3, 0.3)) if outcome == "saved" else self.own((105, 34 if goal else 39), r.side)
            self.flight = dict(kind="shot", start=self.ball, end=end, born=self.engine.t,
                               duration=max(0.4, distance(self.ball, end) / 22), side=r.side,
                               shooter=r, xg=xg, outcome=outcome, keeper=keeper)
            self.owner = None
            return
        candidates = [p for p in self.runners.values() if p.side == r.side and p is not r
                      and 5 < distance(p.xy, r.xy) < 36 and p.player.role != "GK"]
        if not candidates and r.player.role == "GK":
            candidates = [p for p in self.runners.values() if p.side == r.side and p is not r and p.player.role != "GK"]
        if candidates:
            def value(p):
                px, _ = self.own(p.xy, p.side)
                space = min(distance(p.xy, d.xy) for d in enemies)
                lane = min(lane_distance(d.xy, self.ball, p.xy) for d in enemies)
                return (px - x) * 0.25 + min(space, 12) + min(lane, 5) * 2.3 - distance(p.xy, r.xy) * 0.13
            receiver = max(candidates, key=value)
            if r.player.role == "GK" or self.pending_pass_kind != "open_play" or pressure < 6 or self.rng.random() < 0.7:
                self.flight = dict(kind="pass", start=self.ball, end=receiver.xy, born=self.engine.t,
                                   duration=max(0.4, distance(self.ball, receiver.xy) / 15), passer=r, receiver=receiver,
                                   pass_kind=self.pending_pass_kind)
                self.owner = None
                self.held_until = 0
                self.pending_pass_kind = "open_play"
        self.next_decision = self.engine.t + self.rng.uniform(1.2, 2.6)

    def finish_pass(self, winner):
        f = self.flight
        passer = f["passer"]
        ex, ey = self.own(self.ball, passer.side)
        complete = winner.side == passer.side
        self.emit("pass", passer, f["start"], end_x=ex, end_y=ey,
                  receiver_id=winner.player.id if complete else None,
                  outcome="complete" if complete else "incomplete", length=round(distance(f["start"], self.ball), 2),
                  height="ground", kind=f.get("pass_kind", "open_play"), difficulty=0.35)
        if not complete:
            self.emit("interception", winner, outcome="won")
        self.take_ball(winner)

    def step(self):
        self.move_players()
        if self.restart_until:
            gap = distance(self.ball, self.restart_point)
            k = min(1, 12 * DT / max(0.001, gap))
            self.ball = tuple(a + (b - a) * k for a, b in zip(self.ball, self.restart_point))
            if self.restart_ready():
                self.restart_until = 0
                self.pending_pass_kind = self.restart_kind
                self.restart_kind = None
                self.take_ball(self.restart_taker)
                self.next_decision = self.engine.t
                self.decide()  # the restart is a kick to a teammate, not a second touch by the taker
            return
        if self.flight:
            f = self.flight
            k = min(1, (self.engine.t - f["born"]) / f["duration"])
            self.ball = tuple(a + (b - a) * k for a, b in zip(f["start"], f["end"]))
            if f["kind"] == "shot":
                if k == 1:
                    if f["outcome"] == "saved" and distance(f["keeper"].xy, self.ball) > 1:
                        return
                    self.emit("shot", f["shooter"], f["start"], xg=f["xg"], outcome=f["outcome"],
                              body_part="right_foot", kind="open_play", keeper_id=f["keeper"].player.id)
                    if f["outcome"] == "saved":
                        self.take_ball(f["keeper"])
                        self.held_until = self.engine.t + 2
                        self.next_decision = self.held_until
                    else:
                        self.begin_restart("kickoff" if f["outcome"] == "goal" else "goal_kick", 1 - f["side"])
                return
            defenders = [r for r in self.runners.values() if r.side != f["passer"].side and distance(r.xy, self.ball) < 1.1]
            if defenders:
                self.finish_pass(min(defenders, key=lambda r: distance(r.xy, self.ball)))
            elif k == 1:
                # A completed pass requires contact. Otherwise everyone pursues the loose ball.
                nearby = min(self.runners.values(), key=lambda r: distance(r.xy, self.ball))
                if distance(nearby.xy, self.ball) < 1.3:
                    self.finish_pass(nearby)
            return
        if self.owner:
            self.ball = self.owner.xy
            if self.engine.t < self.held_until:
                return
            if self.held_until and self.owner.player.role == "GK":
                self.decide()  # possession in the hands cannot be taken by a tackle
                return
            closest = min((r for r in self.runners.values() if r.side != self.side), key=lambda r: distance(r.xy, self.ball))
            if distance(closest.xy, self.ball) < 1.0 and self.engine.t >= self.next_decision - 0.3:
                self.carry_event()
                self.emit("tackle", closest, outcome="won")
                self.take_ball(closest)
            elif self.engine.t >= self.next_decision:
                self.decide()

    def frame(self):
        home = self.engine.teams[0].id
        return dict(type="frame", source="synthetic", t=round(self.engine.t, 1), period=1, ref_team_id=home,
                    phase=self.restart_kind or ("keeper_ball" if self.engine.t < self.held_until else "open_play"),
                    carrier_id=self.owner.player.id if self.owner else None,
                    possession_team_id=self.engine.teams[self.restart_side if self.restart_kind else self.side].id,
                    players=[dict(id=pid, team_id=self.engine.teams[r.side].id,
                                  x=round(self.own(r.xy, r.side)[0], 3), y=round(self.own(r.xy, r.side)[1], 3),
                                  speed=round(math.hypot(*r.velocity), 3), confidence=1.0)
                             for pid, r in self.runners.items()],
                    ball=dict(x=round(self.ball[0], 3), y=round(self.ball[1], 3), confidence=1.0))

    def run(self, duration=DURATION):
        self.engine.possession_id = 1
        self.begin_restart("kickoff", 0)
        self.restart_until = 2
        self.emit("match_state", state="kickoff")
        self.frames.append(self.frame())
        for tick in range(1, round(duration / DT) + 1):
            self.engine.t = round(tick * DT, 1)
            self.step()
            self.frames.append(self.frame())
        self.emit("match_state", state="full_time")
        meta = self.engine.meta()
        meta["tracking"] = {"kind": "simulation", "hz": 5, "duration": duration}
        meta["match"]["competition"] = "Continuous simulation prototype"
        return meta, self.engine.events, self.frames


@functools.lru_cache(maxsize=1)
def prototype():
    from pitch_insights.explain.simulation import measure_frame
    meta, events, frames = ContinuousMatch().run()
    for frame in frames:
        frame["analysis"] = measure_frame(frame, meta)
    return meta, events, frames


def summary():
    # Listing matches must not generate six minutes of tracking data.
    clubs = load_clubs()
    def club(cid):
        c = clubs[cid]
        return dict(id=c.id, name=c.name, short_name=c.short_name, colours=c.colours)
    return dict(name=NAME, match_id="SIM-42", kind="synthetic", tracking=True,
                home=club("POT"), away=club("CAR"))
