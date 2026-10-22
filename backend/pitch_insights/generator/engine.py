"""The synthetic match engine: a loop of possessions that writes v1 events.

Coordinates inside the engine are always in the current attacking team's frame
(x = 105 is the goal they attack). Defending players are converted with
`flip()` whenever an event is written for them.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from pitch_insights.events.schema import (
    PITCH_LENGTH, PITCH_WIDTH, SCHEMA_VERSION, MatchMeta, display_clock, dump, event_adapter,
)
from pitch_insights.generator.players import (
    FORMATIONS, ClubDef, PlayerDef, club_strength, league_info, load_clubs,
    head_to_head, pick_lineup, player_history, team_history,
)
from pitch_insights.generator.script import Script
from pitch_insights.generator.xg import distance_to_goal, expected_goals

STYLE = {
    #             preferred pass length, spread, forward bias, long-ball rate, press rate,
    #             defensive line, shot rate, cross rate, carry rate, long goal kicks
    "possession": dict(pref_len=13, spread=10, prog=0.8, long_ball=0.02, press=0.32, line=3, shot=0.72, cross=0.22, carry=1.0, gk_long=0.1),
    "high_press": dict(pref_len=15, spread=11, prog=1.1, long_ball=0.05, press=0.45, line=8, shot=0.7, cross=0.3, carry=1.0, gk_long=0.35),
    "direct":     dict(pref_len=22, spread=16, prog=1.5, long_ball=0.18, press=0.3, line=0, shot=1.5, cross=0.55, carry=0.8, gk_long=0.8),
    "counter":    dict(pref_len=18, spread=13, prog=1.4, long_ball=0.1, press=0.22, line=-8, shot=1.5, cross=0.35, carry=1.3, gk_long=0.6),
}
DEFENSIVE_ROLES = {"GK", "LB", "RB", "LCB", "RCB"}


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def flip(x: float, y: float) -> tuple[float, float]:
    return PITCH_LENGTH - x, PITCH_WIDTH - y


def clamp_xy(x: float, y: float) -> tuple[float, float]:
    return min(PITCH_LENGTH, max(0.0, x)), min(PITCH_WIDTH, max(0.0, y))


def in_box(x: float, y: float) -> bool:
    return x > 88.5 and 13.85 < y < 54.15


@dataclass
class PState:
    pdef: PlayerDef
    role: str
    anchor: tuple[float, float]
    form: int
    on_minute: float = 0.0
    on: bool = True
    yellow: bool = False
    fouls: int = 0
    perf: float = 0.0

    @property
    def id(self) -> str:
        return self.pdef.id


@dataclass
class TeamState:
    club: ClubDef
    is_home: bool
    players: list[PState]
    bench: list[PlayerDef]
    form: dict[str, int]
    goals: int = 0
    subs_used: int = 0
    windows: int = 0
    pending_red: bool = False
    pending_sub: bool = False
    forced_done: set = field(default_factory=set)

    @property
    def id(self) -> str:
        return self.club.id

    @property
    def style(self) -> dict:
        return STYLE[self.club.style]

    @property
    def on_pitch(self) -> list[PState]:
        return [p for p in self.players if p.on]

    @property
    def keeper(self) -> PState | None:
        return next((p for p in self.on_pitch if p.role == "GK"), None)


class MatchEngine:
    def __init__(self, seed: int, home: ClubDef, away: ClubDef, script: Script | None = None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.script = script or Script()
        self.match_id = f"SYN-{seed}"
        self.home_club, self.away_club = home, away
        self.teams = [self._team_state(home, True), self._team_state(away, False)]
        self.initial_bench = [list(t.bench) for t in self.teams]
        self.events: list[dict] = []
        self.seq = 0
        self.period = 1
        self.t = 0.0
        self.possession_id = 0
        self.att = 0
        self.carrier: PState | None = None
        self.bx = self.by = 0.0
        self.last_aerial = False
        self.transition = 0  # actions left in a fast break after winning the ball deep
        self.restart: tuple | None = None
        self.period_counts = {"goals": 0, "cards": 0, "windows": 0}

    # ------------------------------------------------------------ setup

    def _team_state(self, club: ClubDef, is_home: bool) -> TeamState:
        lineup = pick_lineup(club, self.rng)
        anchors = {role: (ax, ay) for role, _, ax, ay in FORMATIONS[club.formation]}
        players = [PState(p, role, anchors[role], lineup.form[p.id]) for role, p in lineup.starting]
        return TeamState(club, is_home, players, list(lineup.bench), lineup.form)

    # ------------------------------------------------------------ clock

    def minute_float(self) -> float:
        """Match minute on the broadcast clock; first-half stoppage time stays at 45, like 45+2'."""
        if self.period == 1:
            return min(45.0, self.t / 60)
        return 45 + self.t / 60

    def clock(self) -> tuple[str, int]:
        return display_clock(self.period, self.t)

    # ------------------------------------------------------------ helpers

    def eff(self, p: PState, attr: str) -> float:
        """Attribute after match form and fatigue."""
        return p.pdef.attributes[attr] + p.form - self.fatigue(p)

    def fatigue(self, p: PState) -> float:
        played = self.minute_float() - p.on_minute
        if played <= 60:
            return 0.0
        team = self.team_of(p)
        rate = (1.25 - p.pdef.attributes["stamina"] / 100) * (1.35 if team.club.style == "high_press" else 1.0)
        return ((played - 60) / 30) ** 1.2 * rate * 14

    def team_of(self, p: PState) -> TeamState:
        return self.teams[0] if p in self.teams[0].players else self.teams[1]

    def mods(self, team: TeamState):
        return self.script.modifiers(team.id, int(self.minute_float()))

    def positions(self, team: TeamState, bx: float, by: float, in_possession: bool) -> dict[str, tuple[float, float]]:
        """Where each on-pitch player is, in this team's own frame, given the ball at (bx, by) in that frame."""
        out = {}
        shift_x = 0.45 * (bx - 52.5)
        line = team.style["line"]
        for p in team.on_pitch:
            ax, ay = p.anchor
            if p.role == "GK":
                x = 5 + max(0.0, bx - 30) * 0.1
                y = 34 + (by - 34) * 0.15
            elif in_possession:
                x = ax + shift_x + 6
                y = 34 + (ay - 34) * 1.15 + 0.3 * (by - 34)
                if bx > 65:  # final third: runners arrive in and around the box
                    k = min(1.0, (bx - 65) / 35)
                    pos = p.pdef.position
                    if pos == "W" or p.role in ("LM", "RM", "LW", "RW"):
                        x += 9 * k
                        y = 34 + (y - 34) * (1 - 0.7 * k)
                    elif pos == "AM":
                        x += 16 * k
                    elif pos == "CM":
                        x += 13 * k
                    elif pos == "FB":
                        x += 4 * k
                    elif pos == "ST":
                        x = min(x - 4 * k, 95.0)
                        y += self.rng.uniform(-6, 6) * k  # the striker drifts to pull defenders
            else:
                x = ax + shift_x - 4 + line
                y = 34 + (ay - 34) * 0.75 + 0.45 * (by - 34)
            x += self.rng.uniform(-1.5, 1.5)
            y += self.rng.uniform(-1.5, 1.5)
            out[p.id] = (min(104.0, max(1.0, x)), min(67.0, max(1.0, y)))
        return out

    def snapshot(self):
        A, D = self.teams[self.att], self.teams[1 - self.att]
        apos = self.positions(A, self.bx, self.by, True)
        dpos_own = self.positions(D, *flip(self.bx, self.by), False)
        dpos = {pid: flip(*xy) for pid, xy in dpos_own.items()}
        return A, D, apos, dpos

    @staticmethod
    def nearest(players: list[PState], pos: dict, x: float, y: float, exclude_gk: bool = True):
        best, best_d = None, 1e9
        for p in players:
            if exclude_gk and p.role == "GK":
                continue
            px, py = pos[p.id]
            d = math.hypot(px - x, py - y)
            if d < best_d:
                best, best_d = p, d
        return best, best_d

    # ------------------------------------------------------------ emitting

    def emit(self, type_: str, team: TeamState | None = None, player: PState | None = None,
             x: float | None = None, y: float | None = None, under_pressure: bool = False, **fields):
        self.seq += 1
        clock, minute = self.clock()
        ev = {
            "schema": SCHEMA_VERSION, "match_id": self.match_id, "seq": self.seq, "source": "synthetic",
            "t": round(self.t, 1), "period": self.period, "clock": clock, "minute": minute, "type": type_,
            "under_pressure": under_pressure, "confidence": 1.0,
        }
        if team is not None:
            ev["team_id"] = team.id
            ev["possession_id"] = self.possession_id
        if player is not None:
            ev["player_id"] = player.id
        if x is not None:
            x, y = clamp_xy(x, y)
            ev["x"], ev["y"] = round(x, 1), round(y, 1)
        for k in ("end_x", "end_y"):
            if k in fields:
                lim = PITCH_LENGTH if k == "end_x" else PITCH_WIDTH
                fields[k] = round(min(lim, max(0.0, fields[k])), 1)
        ev.update(fields)
        self.events.append(dump(event_adapter.validate_python(ev)))

    def set_possession(self, team_idx: int, carrier: PState, x: float, y: float):
        if team_idx != self.att or self.possession_id == 0:
            self.possession_id += 1
        self.att = team_idx
        self.transition = 0
        self.carrier = carrier
        self.bx, self.by = clamp_xy(x, y)
        self.last_aerial = False

    def turnover(self, new_carrier: PState, x_new_frame: float, y_new_frame: float):
        self.set_possession(1 - self.att, new_carrier, x_new_frame, y_new_frame)
        team = self.teams[self.att]
        if x_new_frame < 55:
            self.transition = 4 if team.club.style == "counter" else 2 if team.club.style == "direct" else 0

    # ------------------------------------------------------------ main loop

    def run(self) -> tuple[dict, list[dict], dict]:
        for period in (1, 2):
            self.play_period(period)
            self.emit("match_state", state="half_time" if period == 1 else "full_time")
        return self.meta(), self.events, self.debug()

    def play_period(self, period: int):
        self.period, self.t = period, 0.0
        self.period_counts = {"goals": 0, "cards": 0, "windows": 0}
        if period == 2:
            self.att = 1  # the away side kicks off the second half, in a possession of its own
            self.possession_id += 1
            for team in self.teams:
                if self.rng.random() < 0.15:
                    self.make_subs(team, 1, half_time=True)
        self.emit("match_state", state="kickoff")
        self.restart = ("kickoff", 0 if period == 1 else 1, 52.5, 34.0)
        period_end = None
        while True:
            if period_end is None and self.t >= 2700:
                period_end = 2700 + self.stoppage_seconds()
            if period_end is not None and self.t >= period_end and not (self.restart and self.restart[0] == "penalty"):
                break  # the half is extended for a penalty, as in real football
            self.check_forced()
            if self.restart:
                self.do_restart()
            else:
                self.open_play()

    def stoppage_seconds(self) -> float:
        c = self.period_counts
        if self.period == 1:
            mins = 1 + c["goals"] * 0.5 + c["cards"] * 0.3 + self.rng.uniform(0, 2)
        else:
            mins = 3 + c["goals"] * 0.5 + c["windows"] * 0.5 + c["cards"] * 0.3 + self.rng.uniform(0, 2)
        return int(mins) * 60 + self.rng.uniform(0, 50)

    def check_forced(self):
        minute = self.minute_float()
        for i, f in enumerate(self.script.forced):
            team = next((t for t in self.teams if t.id == f.team), None)
            if team is None or i in team.forced_done or minute < f.minute:
                continue
            team.forced_done.add(i)
            if f.type == "red_card":
                team.pending_red = True
            else:
                team.pending_sub = True

    # ------------------------------------------------------------ open play

    def open_play(self):
        A, D, apos, dpos = self.snapshot()
        c = self.carrier
        if c is None or not c.on:
            c, _ = self.nearest(A.on_pitch, apos, self.bx, self.by, exclude_gk=False)
            self.carrier = c
        d, dist = self.nearest(D.on_pitch, dpos, self.bx, self.by, exclude_gk=self.bx < 95)
        mA, mD = self.mods(A), self.mods(D)

        fast_break = self.transition > 0
        if fast_break:
            self.transition -= 1
        under_pressure = dist < 2.5
        press_p = D.style["press"] + mD.press + (self.eff(d, "pressing") - 70) / 150
        if fast_break:
            press_p *= 0.4
        if D.club.style == "high_press" and self.bx < 55:
            press_p *= 1.3
        if D.club.style == "counter" and self.bx < 50:
            press_p *= 0.5
        if dist < 8 and self.rng.random() < press_p * 1.7 * (1.2 - dist / 8):
            self.emit("pressure", D, d, *flip(*dpos[d.id]), target_player_id=c.id)
            under_pressure = True

        if dist < 3.0 and c.role != "GK" and not fast_break and self.rng.random() < 0.31 + mD.press * 0.1:
            self.challenge(A, D, d, c, dpos)
            return

        dgoal = distance_to_goal(self.bx, self.by)
        header_chance = self.last_aerial and dgoal < 14
        shot_w = 0.0
        if c.role != "GK" and self.bx > 75 and dgoal < 30:
            base = 0.24 if dgoal < 8 else 0.15 if dgoal < 12 else 0.12 if dgoal < 18 else 0.11 if dgoal < 24 else 0.05
            if header_chance:
                base = 0.4
            role_mult = {"ST": 0.65, "W": 1.25, "AM": 1.45, "CM": 1.35, "DM": 1.0}.get(c.pdef.position, 1.0)
            block = {"counter": 0.72, "direct": 0.9, "possession": 1.0, "high_press": 1.05}[D.club.style]
            shot_w = 0.95 * base * block * role_mult * (self.eff(c, "shooting") / 75) ** 0.5 * A.style["shot"] * (1 + mA.attack) * (1.05 if A.is_home else 1.0)
            if c.role in DEFENSIVE_ROLES and not header_chance:
                shot_w *= 0.4
        dribble_w = max(0.0, 0.03 + (self.eff(c, "dribbling") - 60) / 400 + (0.05 if self.bx > 60 else 0)) if dist < 5 and c.role != "GK" else 0.0
        carry_w = 0.0 if c.role == "GK" else 0.16 * (2.2 if fast_break else 1.0) * A.style["carry"] * (self.eff(c, "pace") / 75) * (1.8 if dist > 10 else 1.0) * (0.5 if under_pressure and self.bx < 35 else 1.0)
        clear_w = 0.35 if (self.bx < 20 and under_pressure and c.role in DEFENSIVE_ROLES) else 0.0
        pass_w = 0.72
        weights = [shot_w, dribble_w, carry_w, clear_w, pass_w]
        action = self.rng.choices(["shot", "dribble", "carry", "clearance", "pass"], weights)[0]

        if action == "shot":
            self.shoot(A, D, c, under_pressure, header=header_chance and self.rng.random() < 0.75)
        elif action == "dribble":
            self.dribble(A, D, c, d, dpos, under_pressure)
        elif action == "carry":
            self.carry(A, D, c, d, dist, dpos, under_pressure)
        elif action == "clearance":
            self.clear(A, D, c, apos, dpos, under_pressure)
        else:
            self.pass_ball(A, D, c, apos, dpos, under_pressure, "open_play",
                           success_bonus=0.7 if fast_break else 0.0, fast_break=fast_break)

    def carry(self, A, D, c, d, dist, dpos, under_pressure):
        if dist < 3.5:
            p_tackle = 0.1 + (self.eff(d, "defending") - self.eff(c, "dribbling")) / 250
            if self.rng.random() < p_tackle:
                self.challenge(A, D, d, c, dpos)
                return
        length = self.rng.uniform(4, 14) * (self.eff(c, "pace") / 75) * A.style["carry"] * (0.6 if under_pressure else 1.0)
        if self.bx > 80:
            length *= 0.5
        angle = math.atan2(34 - self.by, 105 - self.bx) * 0.5 + self.rng.gauss(0, 0.6)
        ex, ey = clamp_xy(self.bx + length * math.cos(angle), self.by + length * math.sin(angle))
        ex, ey = min(ex, 94.0), min(66.0, max(2.0, ey))
        moved = math.hypot(ex - self.bx, ey - self.by)
        duration = moved / (4.5 + self.eff(c, "pace") / 30)
        if moved > 3:
            self.emit("carry", A, c, self.bx, self.by, under_pressure, end_x=ex, end_y=ey, duration=round(duration, 1))
        self.t += duration + 0.3
        self.bx, self.by = ex, ey
        self.last_aerial = False

    def dribble(self, A, D, c, d, dpos, under_pressure):
        p = sigmoid((self.eff(c, "dribbling") - self.eff(d, "defending")) / 12 + 0.2)
        won = self.rng.random() < p
        self.emit("dribble", A, c, self.bx, self.by, under_pressure, outcome="won" if won else "lost", opponent_id=d.id)
        self.t += self.rng.uniform(1.0, 2.0)
        if won:
            c.perf += 0.15
            self.bx, self.by = clamp_xy(self.bx + self.rng.uniform(3, 6), self.by + self.rng.uniform(-2, 2))
            self.bx = min(self.bx, 103.0)
            self.last_aerial = False
        else:
            c.perf -= 0.1
            self.challenge(A, D, d, c, dpos, after_dribble=True)

    def challenge(self, A, D, d, c, dpos, after_dribble=False):
        """A defender near carrier c challenges: a foul, a failed tackle, or the defender wins the ball."""
        if not after_dribble:
            near = [p for p in D.on_pitch if p.role != "GK"
                    and math.hypot(dpos[p.id][0] - self.bx, dpos[p.id][1] - self.by) < 6]
            if len(near) > 1:
                d = self.rng.choices(near, [1 / (1 + math.hypot(dpos[p.id][0] - self.bx, dpos[p.id][1] - self.by)) for p in near])[0]
        foul_p = 0.68 + (0.06 if D.club.style == "high_press" else 0) + (0.05 if after_dribble else 0)
        if in_box(self.bx, self.by):
            foul_p *= 0.09  # defenders rarely risk a penalty
        if d.yellow:
            foul_p *= 0.35  # booked players ease off
        foul_p *= 0.75 ** d.fouls
        if D.pending_red or self.rng.random() < foul_p:
            self.foul(A, D, d, c, dpos)
            return
        if not after_dribble and self.rng.random() < 0.3 + (self.eff(c, "dribbling") - self.eff(d, "defending")) / 200:
            self.emit("tackle", D, d, *flip(*dpos[d.id]), outcome="lost")
            c.perf += 0.05
            self.t += self.rng.uniform(0.8, 1.5)
            return
        self.emit("tackle", D, d, *flip(*dpos[d.id]), outcome="won")
        d.perf += 0.15
        c.perf -= 0.1
        self.t += self.rng.uniform(1.0, 2.5)
        self.turnover(d, *flip(self.bx, self.by))

    def foul(self, A, D, d, c, dpos):
        card = "none"
        if D.pending_red:
            card, D.pending_red = "red", False
        else:
            r = self.rng.random()
            if r < 0.0025:
                card = "red"
            elif r < (0.07 if d.yellow else 0.19):
                card = "red" if d.yellow else "yellow"
        d.fouls += 1
        if card == "yellow":
            d.yellow = True
        penalty = in_box(self.bx, self.by)
        self.emit("foul", D, d, *flip(*dpos[d.id]), victim_id=c.id, card=card, penalty=penalty)
        if card != "none":
            self.period_counts["cards"] += 1
            d.perf -= 0.4
            self.t += 15
        if card == "red":
            d.on = False
        self.t += self.rng.uniform(15, 35)
        att_idx = self.att
        if penalty:
            self.restart = ("penalty", att_idx, 94.0, 34.0)
        elif distance_to_goal(self.bx, self.by) < 28 and self.bx > 77 and self.rng.random() < 0.4:
            self.restart = ("free_kick_shot", att_idx, self.bx, self.by)
        else:
            self.restart = ("free_kick", att_idx, self.bx, self.by)

    def clear(self, A, D, c, apos, dpos, under_pressure):
        ex = self.bx + self.rng.uniform(30, 55)
        ey = self.rng.uniform(5, 63)
        self.emit("clearance", A, c, self.bx, self.by, under_pressure, outcome="won")
        self.t += self.rng.uniform(2.5, 4.0)
        if self.rng.random() < 0.2:
            self.t += self.rng.uniform(15, 25)
            self.restart = ("corner", 1 - self.att, 104.5, 0.5 if self.by > 34 else 67.5)
            return
        self.bx, self.by = clamp_xy(ex, ey)
        A2, D2, apos2, dpos2 = self.snapshot()
        if self.rng.random() < 0.55:
            r, _ = self.nearest(D.on_pitch, dpos2, self.bx, self.by)
            self.emit("recovery", D, r, *flip(*dpos2[r.id]), outcome="won")
            self.turnover(r, *flip(self.bx, self.by))
        else:
            r, _ = self.nearest(A.on_pitch, apos2, self.bx, self.by)
            self.emit("recovery", A, r, *apos2[r.id], outcome="won")
            self.carrier, self.last_aerial = r, False

    # ------------------------------------------------------------ passing

    def pass_ball(self, A, D, c, apos, dpos, under_pressure, kind, targets=None, end=None, success_bonus=0.0,
                  fast_break=False):
        mA = self.mods(A)
        style = A.style
        mates = targets or [p for p in A.on_pitch if p is not c and (p.role != "GK" or self.bx < 40)]
        wide = self.by < 16 or self.by > 52
        if kind == "open_play":
            if self.bx > 75 and wide and self.rng.random() < style["cross"] * (1.2 if "crosser" in c.pdef.traits else 1.0) * 0.5:
                kind = "cross"
            elif self.bx < 60 and self.rng.random() < style["long_ball"] + mA.directness * 0.2:
                kind = "long_ball"

        if kind in ("cross", "corner") or (kind == "free_kick" and self.bx > 75):
            ex, ey = (self.rng.uniform(90, 101), self.rng.uniform(26, 42)) if end is None else end
            cands = [p for p in mates if p.role not in ("GK",)]
            weights = [(self.eff(p, "aerial") / 70) ** 1.2 / (1 + math.hypot(apos[p.id][0] - ex, apos[p.id][1] - ey) / 6) for p in cands]
            target = self.rng.choices(cands, weights)[0]
        else:
            pref = style["pref_len"] * (1 + mA.directness)
            spread = style["spread"]
            if kind in ("long_ball", "goal_kick") and pref < 30:
                pref, spread = 40, 14
            cands, weights = [], []
            for p in mates:
                tx, ty = apos[p.id]
                L = math.hypot(tx - self.bx, ty - self.by)
                if L < 3:
                    continue
                fwd = tx - self.bx
                _, open_d = self.nearest(D.on_pitch, dpos, tx, ty, exclude_gk=False)
                w = math.exp(-(((L - pref) / spread) ** 2))
                w *= (1 + max(0.0, fwd) / 20 * style["prog"] * (1 + mA.attack) * (2.0 if fast_break else 1.0)) if fwd > 0 else 0.7
                w *= min(1.0, open_d / 8) + 0.2
                if kind == "long_ball" and fwd < 15:
                    w *= 0.1
                if self.bx > 65 and p.pdef.position == "ST":
                    w *= 0.55  # the striker is marked tightly in the final third
                cands.append(p)
                weights.append(w)
            if not cands:
                cands, weights = mates, [1.0] * len(mates)
            target = self.rng.choices(cands, weights)[0]
            tx, ty = apos[target.id]
            if (kind == "open_play" and tx - self.bx > 10 and tx > 70
                    and self.rng.random() < max(0.0, (self.eff(c, "vision") - 60) / 120)):
                kind = "through_ball"
                tx += self.rng.uniform(3, 8)
            ex, ey = (tx + self.rng.gauss(0, 1.5), ty + self.rng.gauss(0, 1.5)) if end is None else end

        ex, ey = min(PITCH_LENGTH, max(0.0, ex)), min(PITCH_WIDTH, max(0.0, ey))
        L = math.hypot(ex - self.bx, ey - self.by)
        fwd = ex - self.bx
        _, end_open = self.nearest(D.on_pitch, dpos, ex, ey, exclude_gk=False)
        logit = (3.4 - 0.06 * L - 0.55 * under_pressure - 0.03 * max(0.0, fwd)
                 + (self.eff(c, "passing") - 72) / 15 - max(0.0, 4 - end_open) * 0.35
                 + (0.15 if A.is_home else 0.0) + success_bonus
                 - (0.7 if in_box(ex, ey) and kind not in ("cross", "corner") else 0.0))
        logit += {"cross": -1.6, "corner": -1.3, "long_ball": -0.6, "through_ball": -1.1,
                  "goal_kick": -0.6, "throw_in": 0.8, "kickoff": 3.0, "free_kick": 0.3}.get(kind, 0.0)
        if kind in ("cross", "through_ball", "corner"):
            logit += (self.eff(c, "vision") - 70) / 40
        p = sigmoid(logit)
        height = "high" if kind in ("cross", "corner", "long_ball", "goal_kick") or L > 32 else "low" if L > 18 else "ground"
        duration = 0.8 + L / 16 + self.rng.uniform(0.7, 2.0)

        if self.rng.random() < p:
            self.emit("pass", A, c, self.bx, self.by, under_pressure, end_x=ex, end_y=ey, receiver_id=target.id,
                      outcome="complete", length=round(L, 1), height=height, kind=kind, difficulty=round(1 - p, 3))
            c.perf += 0.02 + (0.1 if fwd > 15 else 0)
            self.t += duration
            self.carrier = target
            self.bx, self.by = clamp_xy(ex, ey)
            self.bx = min(self.bx, 104.0)
            self.last_aerial = height == "high"
            return

        c.perf -= 0.06
        out = ey <= 0.5 or ey >= 67.5 or ex >= 104.5 or (self.rng.random() < 0.12 and height != "ground")
        self.emit("pass", A, c, self.bx, self.by, under_pressure, end_x=ex, end_y=ey,
                  outcome="out" if out else "incomplete", length=round(L, 1), height=height, kind=kind,
                  difficulty=round(1 - p, 3))
        self.t += duration
        if out:
            self.t += self.rng.uniform(8, 20)
            if ex >= 100:
                if kind in ("cross", "corner") and self.rng.random() < 0.55:
                    self.restart = ("corner", self.att, 104.5, 0.5 if ey < 34 else 67.5)
                else:
                    self.restart = ("goal_kick", 1 - self.att, 5.5, 34.0)
            else:
                ox, oy = flip(min(ex, 100.0), 0.5 if ey < 34 else 67.5)
                self.restart = ("throw_in", 1 - self.att, ox, oy)
            return
        self.bx, self.by = ex, ey
        A2, D2, apos2, dpos2 = self.snapshot()
        r, _ = self.nearest(D.on_pitch, dpos2, ex, ey, exclude_gk=not in_box(ex, ey))
        if in_box(ex, ey) and height == "high":
            if r.role == "GK" or self.rng.random() < 0.25:
                gk = D.keeper or r
                self.emit("recovery", D, gk, *flip(ex, ey), outcome="won")
                self.turnover(gk, *flip(ex, ey))
            else:
                self.emit("clearance", D, r, *flip(ex, ey), outcome="won")
                self.t += 2
                if self.rng.random() < 0.45:
                    self.restart = ("corner", self.att, 104.5, 0.5 if ey < 34 else 67.5)
                    self.t += self.rng.uniform(15, 25)
                else:
                    self.second_ball(A, D)
            return
        ev = "interception" if L < 30 and self.rng.random() < 0.6 else "recovery"
        self.emit(ev, D, r, *flip(ex, ey), outcome="won")
        r.perf += 0.08
        self.t += 0.5
        self.turnover(r, *flip(ex, ey))

    def second_ball(self, A, D):
        """After a clearance from the defending team's box: someone picks up the loose ball."""
        lx, ly = self.rng.uniform(55, 75), self.rng.uniform(10, 58)
        self.bx, self.by = lx, ly
        A2, D2, apos2, dpos2 = self.snapshot()
        if self.rng.random() < 0.5:
            r, _ = self.nearest(A.on_pitch, apos2, lx, ly)
            self.emit("recovery", A, r, lx, ly, outcome="won")
            self.carrier, self.last_aerial = r, False
        else:
            r, _ = self.nearest(D.on_pitch, dpos2, lx, ly)
            self.emit("recovery", D, r, *flip(lx, ly), outcome="won")
            self.turnover(r, *flip(lx, ly))
        self.t += 1.5

    # ------------------------------------------------------------ shooting

    def shoot(self, A, D, c, under_pressure, header=False, kind=None):
        kind = kind or ("header" if header else "open_play")
        body = "head" if header else (f"{c.pdef.foot}_foot" if self.rng.random() < 0.8 else
                                      ("left_foot" if c.pdef.foot == "right" else "right_foot"))
        xg = expected_goals(self.bx, self.by, header=header, under_pressure=under_pressure, kind=kind)
        gk = D.keeper
        skill = self.eff(c, "aerial" if header else "shooting")
        p_goal = 0.95 * xg * (1 + (skill - 80) / 150) * (1 - ((self.eff(gk, "goalkeeping") if gk else 40) - 75) / 150)
        p_goal *= 1.05 if A.is_home else 1.0
        dgoal = distance_to_goal(self.bx, self.by)
        r = self.rng.random()
        if r < p_goal:
            outcome = "goal"
        else:
            r2 = self.rng.random()
            block_p = 0.0 if kind == "penalty" else (0.24 + 0.1 * under_pressure if dgoal > 9 else 0.08)
            if D.club.style == "counter" and kind != "penalty":
                block_p += 0.06  # a deep block gets bodies in the way
            if r2 < block_p:
                outcome = "blocked"
            elif r2 < block_p + 0.03:
                outcome = "woodwork"
            elif r2 < block_p + 0.03 + (1 - block_p) * 0.42:
                outcome = "saved"
            else:
                outcome = "off_target"
        keeper_id = gk.id if gk and outcome in ("goal", "saved") else None
        fields = dict(xg=xg, outcome=outcome, body_part=body, kind=kind)
        if keeper_id:
            fields["keeper_id"] = keeper_id
        self.emit("shot", A, c, self.bx, self.by, under_pressure, **fields)
        self.t += 1.5
        self.last_aerial = False
        c.perf += 0.1 + (0.2 if outcome in ("goal", "saved") else 0)

        if outcome == "goal":
            c.perf += 1.0
            A.goals += 1
            self.period_counts["goals"] += 1
            self.t += self.rng.uniform(50, 75)
            self.restart = ("kickoff", 1 - self.att, 52.5, 34.0)
        elif outcome == "saved":
            if gk:
                gk.perf += 0.2
            if self.rng.random() < 0.4:
                self.t += self.rng.uniform(15, 25)
                self.restart = ("corner", self.att, 104.5, 0.5 if self.by < 34 else 67.5)
            elif gk:
                self.t += self.rng.uniform(3, 8)
                self.turnover(gk, 8.0, 34.0)
            else:
                self.second_ball(A, D)
        elif outcome == "blocked":
            r3 = self.rng.random()
            if r3 < 0.52:
                self.t += self.rng.uniform(15, 25)
                self.restart = ("corner", self.att, 104.5, 0.5 if self.by < 34 else 67.5)
            else:
                A2, D2, apos2, dpos2 = self.snapshot()
                if r3 < 0.7:
                    rd, _ = self.nearest(D.on_pitch, dpos2, self.bx, self.by)
                    self.emit("recovery", D, rd, *flip(self.bx, self.by), outcome="won")
                    self.turnover(rd, *flip(self.bx, self.by))
                else:
                    ra, _ = self.nearest([p for p in A.on_pitch if p is not c] or A.on_pitch, apos2, self.bx, self.by)
                    self.bx = max(70.0, self.bx - 6)
                    self.emit("recovery", A, ra, self.bx, self.by, outcome="won")
                    self.carrier = ra
                self.t += 1.0
        elif outcome == "woodwork" and self.rng.random() < 0.5:
            self.second_ball(A, D)
        elif outcome == "off_target" and self.rng.random() < 0.2:
            self.t += self.rng.uniform(15, 25)
            self.restart = ("corner", self.att, 104.5, 0.5 if self.by < 34 else 67.5)
        else:
            self.t += self.rng.uniform(15, 25)
            self.restart = ("goal_kick", 1 - self.att, 5.5, 34.0)

    # ------------------------------------------------------------ restarts

    def do_restart(self):
        kind, team_idx, x, y = self.restart
        self.restart = None
        if kind != "penalty":
            for team in self.teams:
                self.maybe_subs(team)
        team = self.teams[team_idx]
        players = team.on_pitch

        def best(attr, roles=None):
            pool = [p for p in players if p.role != "GK" and (roles is None or p.role in roles or p.pdef.position in roles)]
            return max(pool or [p for p in players if p.role != "GK"], key=lambda p: self.eff(p, attr))

        if kind == "kickoff":
            taker = next((p for p in players if p.pdef.position == "ST"), best("passing"))
        elif kind == "goal_kick":
            taker = team.keeper or best("passing")
        elif kind == "throw_in":
            apos = self.positions(team, x, y, True)
            taker, _ = self.nearest([p for p in players if p.role != "GK"], apos, x, y)
        elif kind == "corner":
            taker = best("passing", {"W", "AM", "FB", "CM"})
        elif kind in ("penalty", "free_kick_shot"):
            taker = best("shooting")
        else:
            taker = best("passing")
        self.set_possession(team_idx, taker, x, y)
        A, D, apos, dpos = self.snapshot()

        if kind == "kickoff":
            mates = [p for p in players if p.pdef.position in ("CM", "DM", "AM") and p is not taker] or None
            self.pass_ball(A, D, taker, apos, dpos, False, "kickoff", targets=mates)
        elif kind == "throw_in":
            near = [p for p in players if p is not taker and p.role != "GK"
                    and math.hypot(apos[p.id][0] - x, apos[p.id][1] - y) < 22]
            self.pass_ball(A, D, taker, apos, dpos, False, "throw_in", targets=near or None)
        elif kind == "goal_kick":
            if self.rng.random() < A.style["gk_long"] + self.mods(A).directness * 0.3:
                fwd = [p for p in players if p.pdef.position in ("ST", "W", "AM")]
                self.pass_ball(A, D, taker, apos, dpos, False, "goal_kick", targets=fwd or None, success_bonus=-0.6)
            else:
                backs = [p for p in players if p.role in ("LCB", "RCB", "LB", "RB")]
                self.pass_ball(A, D, taker, apos, dpos, False, "goal_kick", targets=backs or None, success_bonus=3.0)
        elif kind == "corner":
            if self.rng.random() < 0.1:
                near = [p for p in players if p is not taker and apos[p.id][0] > 85]
                self.pass_ball(A, D, taker, apos, dpos, False, "corner", targets=near or None, success_bonus=3.0,
                               end=(self.rng.uniform(96, 100), self.rng.uniform(8, 60)))
            else:
                self.pass_ball(A, D, taker, apos, dpos, False, "corner")
        elif kind == "free_kick":
            self.pass_ball(A, D, taker, apos, dpos, False, "free_kick")
        elif kind == "free_kick_shot":
            self.shoot(A, D, taker, False, kind="free_kick")
        elif kind == "penalty":
            self.shoot(A, D, taker, False, kind="penalty")

    # ------------------------------------------------------------ substitutions

    def maybe_subs(self, team: TeamState):
        minute = self.minute_float()
        if team.subs_used >= 5 or team.windows >= 3:
            team.pending_sub = False
            return
        if team.pending_sub:
            team.pending_sub = False
            self.make_subs(team, 1)
            return
        if self.period != 2 or minute < 55:
            return
        if self.rng.random() < 0.045 + 0.005 * (minute - 55):
            n = self.rng.choices([1, 2, 3], [0.4, 0.42, 0.18])[0]
            if team.windows == 2:
                n = max(n, 5 - team.subs_used)
            self.make_subs(team, min(n, 5 - team.subs_used))

    def make_subs(self, team: TeamState, n: int, half_time: bool = False):
        outfield = [p for p in team.on_pitch if p.role != "GK"]
        scored = sorted(outfield, key=lambda p: -(self.fatigue(p) / 5 + (0.6 if p.yellow else 0)
                                                   - p.perf * 0.5 + self.rng.uniform(0, 0.5)))
        done = 0
        for off in scored:
            if done >= n or team.subs_used >= 5:
                break
            accepted = next(acc for role, acc, _, _ in FORMATIONS[team.club.formation] if role == off.role)
            options = [b for b in team.bench if b.position in accepted] or [b for b in team.bench if b.position != "GK"]
            if not options:
                break
            on_def = max(options, key=lambda b: b.quality - accepted.index(b.position) * 6 if b.position in accepted else b.quality - 20)
            team.bench.remove(on_def)
            off.on = False
            new = PState(on_def, off.role, off.anchor, team.form[on_def.id], on_minute=self.minute_float())
            team.players.append(new)
            if self.carrier is off:
                self.carrier = new
            self.emit("substitution", team, None, player_off_id=off.id, player_on_id=new.id)
            team.subs_used += 1
            done += 1
        if done and not half_time:
            team.windows += 1
            self.period_counts["windows"] += 1
            self.t += 25

    # ------------------------------------------------------------ outputs

    def meta(self) -> dict:
        league, matchday = league_info()
        mrng = random.Random(self.seed * 7919 + 1)
        matchday = matchday + mrng.randint(-4, 10)

        def team_block(ts: TeamState, h2h: dict, starters: list[PState], bench: list[PlayerDef]):
            ranked = sorted(ts.club.players, key=lambda p: -p.quality)
            players = [dict(id=p.id, name=p.name, number=p.number, position=p.position, foot=p.foot,
                            attributes=p.attributes, history=player_history(p, matchday, ranked.index(p), mrng))
                       for p in ts.club.players]
            return dict(id=ts.id, name=ts.club.name, short_name=ts.club.short_name, colours=ts.club.colours,
                        formation=ts.club.formation, style=ts.club.style,
                        starting=[p.id for p in starters], bench=[p.id for p in bench],
                        players=players, history=team_history(ts.club, h2h, mrng))

        home, away = self.teams
        h2h_home, h2h_away = head_to_head(home.club, away.club, mrng)
        meta = dict(
            type="match_meta", schema=SCHEMA_VERSION,
            match=dict(id=self.match_id, seed=self.seed, date="2026-10-24", competition=league,
                       matchday=matchday, venue=home.club.venue),
            home=team_block(home, h2h_home, home.players[:11], self.initial_bench[0]),
            away=team_block(away, h2h_away, away.players[:11], self.initial_bench[1]),
            attacking_direction={
                "1": {home.id: "left_to_right", away.id: "right_to_left"},
                "2": {home.id: "right_to_left", away.id: "left_to_right"},
            },
        )
        return dump(MatchMeta.model_validate(meta))

    def debug(self) -> dict:
        return dict(
            match_id=self.match_id, seed=self.seed,
            form={t.id: t.form for t in self.teams},
            script=dict(phases=[vars(p) for p in self.script.phases], forced=[vars(f) for f in self.script.forced]),
            strength={t.id: round(club_strength(t.club), 1) for t in self.teams},
        )


def simulate(seed: int, home_id: str | None = None, away_id: str | None = None,
             script: Script | None = None) -> tuple[dict, list[dict], dict]:
    """Generate one full match. Returns (match_meta, events, match_debug)."""
    clubs = load_clubs()
    script = script or Script()
    home_id = home_id or script.home
    away_id = away_id or script.away
    if not home_id or not away_id:
        pick = random.Random(seed ^ 0x5EED).sample(sorted(clubs), 2)
        if not home_id and not away_id:
            home_id, away_id = pick
        elif not away_id:
            away_id = pick[1] if pick[1] != home_id else pick[0]
        else:
            home_id = pick[0] if pick[0] != away_id else pick[1]
    if home_id == away_id:
        raise ValueError("home and away must be different clubs")
    for item in (*script.phases, *script.forced):
        if item.team not in (home_id, away_id):
            raise ValueError(f"script refers to {item.team!r}, which isn't playing ({home_id} v {away_id})")
    engine = MatchEngine(seed, clubs[home_id], clubs[away_id], script)
    return engine.run()
