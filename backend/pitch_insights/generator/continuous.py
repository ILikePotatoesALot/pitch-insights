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
        if runner.side != self.side:
            self.engine.possession_id += 1
        self.side = runner.side
        self.owner = runner
        self.flight = None
        self.next_decision = self.engine.t + self.rng.uniform(0.8, 1.8)
        self.carry_start = (self.engine.t, runner.xy)

    def targets(self):
        targets = {}
        for side, team in enumerate(self.engine.teams):
            bx, by = self.own(self.ball, side)
            members = [r for r in self.runners.values() if r.side == side]
            pressers = sorted((r for r in members if r.player.role != "GK"), key=lambda r: distance(r.xy, self.ball))[:2]
            for r in members:
                ax, ay = r.player.anchor
                if self.restart_until:
                    target = (min(48, ax * 0.65), ay)
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
                if r is self.owner and not self.restart_until:
                    target = (min(99, bx + 10), by + (34 - by) * 0.2)
                target = (max(2, min(103, target[0])), max(2, min(66, target[1])))
                targets[r.player.id] = self.own(target, side)
        if self.flight and self.flight["kind"] == "pass":
            targets[self.flight["receiver"].player.id] = self.flight["end"]
        if self.restart_until:
            taker = min((r for r in self.runners.values() if r.side == self.restart_side and r.player.role != "GK"),
                        key=lambda r: distance(r.xy, (52.5, 34)))
            targets[taker.player.id] = (52.5, 34)
        return targets

    def move_players(self):
        targets = self.targets()
        for pid, r in self.runners.items():
            tx, ty = targets[pid]
            dx, dy = tx - r.xy[0], ty - r.xy[1]
            gap = math.hypot(dx, dy)
            vmax = 4.8 + r.player.pdef.attributes["pace"] * 0.035
            if r is self.owner:
                vmax *= 0.72
            speed = min(vmax, gap * 1.8)
            desired = (dx / max(gap, 0.001) * speed, dy / max(gap, 0.001) * speed)
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
        if x > 82 and abs(y - 34) < 22:
            xg = expected_goals(x, y, under_pressure=pressure < 4)
            goal = self.rng.random() < min(0.75, xg * r.player.pdef.attributes["shooting"] / 65)
            keeper = next(p for p in enemies if p.player.role == "GK")
            outcome = "goal" if goal else self.rng.choice(["saved", "off_target"])
            end = keeper.xy if outcome == "saved" else self.own((105, 34 if goal else 39), r.side)
            self.flight = dict(kind="shot", start=self.ball, end=end, born=self.engine.t,
                               duration=max(0.4, distance(self.ball, end) / 22), side=r.side,
                               shooter=r, xg=xg, outcome=outcome, keeper=keeper)
            self.owner = None
            return
        candidates = [p for p in self.runners.values() if p.side == r.side and p is not r
                      and 5 < distance(p.xy, r.xy) < 36 and p.player.role != "GK"]
        if candidates:
            def value(p):
                px, _ = self.own(p.xy, p.side)
                space = min(distance(p.xy, d.xy) for d in enemies)
                lane = min(lane_distance(d.xy, self.ball, p.xy) for d in enemies)
                return (px - x) * 0.55 + min(space, 12) + min(lane, 5) * 1.8 - distance(p.xy, r.xy) * 0.13
            receiver = max(candidates, key=value)
            if pressure < 6 or self.rng.random() < 0.65:
                self.flight = dict(kind="pass", start=self.ball, end=receiver.xy, born=self.engine.t,
                                   duration=max(0.4, distance(self.ball, receiver.xy) / 15), passer=r, receiver=receiver)
                self.owner = None
        self.next_decision = self.engine.t + self.rng.uniform(1.2, 2.6)

    def finish_pass(self, winner):
        f = self.flight
        passer = f["passer"]
        ex, ey = self.own(self.ball, passer.side)
        complete = winner.side == passer.side
        self.emit("pass", passer, f["start"], end_x=ex, end_y=ey,
                  receiver_id=winner.player.id if complete else None,
                  outcome="complete" if complete else "incomplete", length=round(distance(f["start"], self.ball), 2),
                  height="ground", kind="open_play", difficulty=0.35)
        if not complete:
            self.emit("interception", winner, outcome="won")
        self.take_ball(winner)

    def step(self):
        self.move_players()
        if self.restart_until:
            # Dead-ball return to the centre; players run back rather than teleporting.
            gap = distance(self.ball, (52.5, 34))
            k = min(1, 12 * DT / max(0.001, gap))
            self.ball = (self.ball[0] + (52.5 - self.ball[0]) * k, self.ball[1] + (34 - self.ball[1]) * k)
            if self.engine.t >= self.restart_until:
                taker = min((r for r in self.runners.values() if r.side == self.restart_side), key=lambda r: distance(r.xy, self.ball))
                if distance(taker.xy, self.ball) < 1:
                    self.restart_until = 0
                    self.take_ball(taker)
            return
        if self.flight:
            f = self.flight
            k = min(1, (self.engine.t - f["born"]) / f["duration"])
            self.ball = tuple(a + (b - a) * k for a, b in zip(f["start"], f["end"]))
            if f["kind"] == "shot":
                if k == 1:
                    self.emit("shot", f["shooter"], f["start"], xg=f["xg"], outcome=f["outcome"],
                              body_part="right_foot", kind="open_play", keeper_id=f["keeper"].player.id)
                    self.restart_side = 1 - f["side"]
                    self.restart_until = self.engine.t + 12
                    self.flight = None
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
                    players=[dict(id=pid, team_id=self.engine.teams[r.side].id,
                                  x=round(self.own(r.xy, r.side)[0], 3), y=round(self.own(r.xy, r.side)[1], 3),
                                  speed=round(math.hypot(*r.velocity), 3), confidence=1.0)
                             for pid, r in self.runners.items()],
                    ball=dict(x=round(self.ball[0], 3), y=round(self.ball[1], 3), confidence=1.0))

    def run(self, duration=DURATION):
        self.engine.possession_id = 1
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
    return ContinuousMatch().run()


def summary():
    # Listing matches must not generate six minutes of tracking data.
    clubs = load_clubs()
    def club(cid):
        c = clubs[cid]
        return dict(id=c.id, name=c.name, short_name=c.short_name, colours=c.colours)
    return dict(name=NAME, match_id="SIM-42", kind="synthetic", tracking=True,
                home=club("POT"), away=club("CAR"))
