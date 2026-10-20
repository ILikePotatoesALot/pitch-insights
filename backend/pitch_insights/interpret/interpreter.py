"""The Interpret stage: turns the event stream into stats, patterns, ratings and signals.

Feed events one at a time with `update()`; it never looks ahead, so it behaves the
same on a live feed as on a replay. `snapshot()` returns the full current state as
JSON-ready data. `update()` returns any *signals* raised by that event: things that
might matter (a goal, a momentum swing, a pressing spell, a rating jump, a
milestone), each with the numbers behind it, for the Moment Scorer to rank.

    interp = Interpreter(meta)
    for ev in events:
        for signal in interp.update(ev):
            ...
    state = interp.snapshot()
"""

from __future__ import annotations

from collections import deque

from pitch_insights.interpret.patterns import Patterns
from pitch_insights.interpret.ratings import Ratings
from pitch_insights.interpret.stats import (
    FINAL_THIRD_X, HALFWAY_X, PlayerStats, TeamStats, is_progressive, threat_added,
)
from pitch_insights.interpret.winprob import prior_rate, win_probability

XT_POINTS = 4.0            # rating points per unit of expected threat added
BIG_CHANCE_XG = 0.30
ERROR_WINDOW_S = 20.0      # a giveaway is an error if the opponent shoots within this time
SEASON_GOAL_MILESTONES = {1, 5, 10, 15, 20, 25, 30}
CAREER_GOAL_MILESTONES = {25, 50, 75, 100, 150, 200}
SEASON_ASSIST_MILESTONES = {5, 10, 15}


class Interpreter:
    def __init__(self, meta: dict):
        self.meta = meta
        self.home, self.away = meta["home"]["id"], meta["away"]["id"]
        self.side = {self.home: "home", self.away: "away"}
        self.other = {self.home: self.away, self.away: self.home}
        self.team = {self.home: TeamStats(), self.away: TeamStats()}
        self.players: dict[str, PlayerStats] = {}
        self.history: dict[str, dict] = {}
        for side in ("home", "away"):
            t = meta[side]
            for p in t["players"]:
                self.players[p["id"]] = PlayerStats(p["id"], t["id"], p["name"], p["position"], p["number"])
                self.history[p["id"]] = p["history"]
            for pid in t["starting"]:
                self.players[pid].on_at = 0.0
        self.ratings = Ratings({pid: p.position for pid, p in self.players.items()})
        self.patterns = Patterns(self.home, self.away)
        self.score = {self.home: 0, self.away: 0}
        self.men = {self.home: 11, self.away: 11}
        self.prior = {self.home: prior_rate(meta["home"]["history"]["league_position"], True),
                      self.away: prior_rate(meta["away"]["history"]["league_position"], False)}
        self.now = 0.0
        self.match_minute = 0.0
        self.clock = "0'"
        self.seq = 0
        self.period = 1
        self.first_half_end: float | None = None
        self.finished = False
        self.possession_team: str | None = None
        self.last_pass: dict | None = None
        self.pending_errors: list[dict] = []
        self.wp = self._win_prob()
        self._wp_minute = 0
        self.signals: list[dict] = []
        self._rating_hist: dict[str, deque] = {pid: deque() for pid in self.players}
        self._rating_marks: dict[str, set] = {pid: set() for pid in self.players}
        self._cooldown: dict[tuple, float] = {}
        self._momentum_extreme: deque = deque()  # (time, smoothed momentum) for swing detection
        self._last_minute_checked = -1

    # ------------------------------------------------------------ helpers

    def _abs_time(self, ev: dict) -> float:
        if ev["period"] == 2:
            return (self.first_half_end or 2700.0) + ev["t"]
        return ev["t"]

    def _clock_label(self, match_seconds: float) -> tuple[int, int]:
        """(period, broadcast minute) for a match time, e.g. 2900 s -> (2, 48) if the first half ended at 2760 s."""
        if self.first_half_end is None or match_seconds < self.first_half_end:
            return 1, int(match_seconds // 60)
        return 2, 45 + int((match_seconds - self.first_half_end) // 60)

    def _win_prob(self) -> dict:
        return win_probability(
            self.score[self.home], self.score[self.away], self.match_minute,
            self.team[self.home].xg, self.team[self.away].xg,
            self.prior[self.home], self.prior[self.away],
            self.men[self.home], self.men[self.away], finished=self.finished)

    def _team_win(self, team: str, wp: dict | None = None) -> float:
        return (wp or self.wp)[self.side[team]]

    def _on_pitch(self, team: str) -> list[PlayerStats]:
        return [p for p in self.players.values()
                if p.team_id == team and p.on_at is not None and p.off_at is None]

    def _rate(self, pid, ev, category, label, points):
        self.ratings.add(pid, ev["seq"], ev["clock"], category, label, points)

    def _signal(self, out: list, type_: str, ev: dict, team: str | None = None, player: str | None = None,
                cooldown_key: tuple | None = None, cooldown_s: float = 0.0, **data) -> None:
        if cooldown_key is not None:
            until = self._cooldown.get(cooldown_key, -1.0)
            if self.now < until:
                return
            self._cooldown[cooldown_key] = self.now + cooldown_s
        s = {"type": type_, "seq": ev["seq"], "clock": ev["clock"], "minute": ev["minute"],
             "period": ev["period"], "match_time": round(self.now, 1)}
        if team:
            s["team_id"] = team
        if player:
            s["player_id"] = player
            s["player_name"] = self.players[player].name
        s["data"] = data
        out.append(s)

    # ------------------------------------------------------------ main entry

    def update(self, ev: dict) -> list[dict]:
        if ev["seq"] <= self.seq:
            raise ValueError(f"events must arrive in order (got seq {ev['seq']} after {self.seq})")
        self.seq = ev["seq"]
        self.period = ev["period"]
        self.clock = ev["clock"]
        if ev["type"] == "match_state" and ev["state"] == "half_time":
            self.first_half_end = ev["t"]
        self.now = self._abs_time(ev)
        self.match_minute = ev["t"] / 60 + (45 if ev["period"] == 2 else 0)
        self.patterns.advance(self.now, self._clock_label)
        out: list[dict] = []

        team = ev.get("team_id")
        # Pressures, fouls, subs and failed tackles are made by a team without the ball; they don't change possession.
        keeps_ball = ev["type"] in ("pressure", "foul", "substitution") or (ev["type"] == "tackle" and ev["outcome"] == "lost")
        if team and "possession_id" in ev and not keeps_ball:
            if self.possession_team is not None and team != self.possession_team:
                self.patterns.add(self.now, "possession_change", None)
                self.last_pass = None
            self.possession_team = team

        handler = getattr(self, f"_on_{ev['type']}", None)
        if handler:
            handler(ev, out)

        # Inputs change only on shots (xG, score), red cards, the end of the match, or as time passes.
        if ev["type"] in ("shot", "foul", "match_state") or int(self.match_minute) != self._wp_minute:
            self.wp = self._win_prob()
            self._wp_minute = int(self.match_minute)
        self._check_ratings(ev, out)
        self._check_patterns(ev, out)
        self.signals.extend(out)
        return out

    # ------------------------------------------------------------ event handlers

    def _touch(self, pid):
        if pid in self.players:
            self.players[pid].touches += 1

    def _on_pass(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        ts, ps = self.team[team], self.players[pid]
        self._touch(pid)
        ts.passes += 1
        ps.passes += 1
        ps.pass_difficulty_sum += ev["difficulty"]
        ps.pass_lengths.append(ev["length"])
        self.patterns.add(self.now, "pass", team)
        if ev["x"] < 63:
            self.team[self.other[team]].opp_passes_own_60 += 1
        if ev["x"] >= FINAL_THIRD_X:
            self.patterns.add(self.now, "final_third_pass", team)
        if ev["kind"] == "cross":
            ts.crosses += 1
            ps.crosses += 1
        if ev["kind"] == "corner":
            ts.corners += 1
        if ev["outcome"] == "complete":
            ts.passes_complete += 1
            ps.passes_complete += 1
            gained = threat_added(ev)
            self._rate(pid, ev, "passing", "completed pass", 0.004 + ev["difficulty"] * 0.02)
            if gained > 0:
                ts.xt_added += gained
                ps.xt_added += gained
                self.patterns.add(self.now, "threat", team, gained)
                self._rate(pid, ev, "passing", "pass that added threat", gained * XT_POINTS)
            if is_progressive(ev):
                ts.progressive_passes += 1
                ps.progressive_passes += 1
                self._rate(pid, ev, "passing", "progressive pass", 0.03)
            if ev["x"] < FINAL_THIRD_X <= ev["end_x"]:
                ts.final_third_entries += 1
            self.last_pass = {"passer": pid, "receiver": ev.get("receiver_id"), "possession": ev.get("possession_id"),
                              "seq": ev["seq"], "kind": ev["kind"]}
        else:
            self._rate(pid, ev, "passing", "misplaced pass", -0.05 * (1 - ev["difficulty"]) - 0.01)
            self.last_pass = None
            if ev["x"] < 35:
                self.pending_errors.append({"player": pid, "team": team, "time": self.now, "what": "gave the ball away"})

    def _on_carry(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        ps = self.players[pid]
        self._touch(pid)
        ps.carries += 1
        gained = threat_added(ev)
        if gained > 0:
            self.team[team].xt_added += gained
            ps.xt_added += gained
            self.patterns.add(self.now, "threat", team, gained)
            self._rate(pid, ev, "attacking", "carry that added threat", gained * XT_POINTS)
        if is_progressive(ev):
            ps.progressive_carries += 1
            self._rate(pid, ev, "attacking", "progressive carry", 0.03)

    def _on_dribble(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        ps = self.players[pid]
        self._touch(pid)
        ps.dribbles += 1
        if ev["outcome"] == "won":
            ps.dribbles_won += 1
            self.team[team].dribbles_won += 1
            self._rate(pid, ev, "attacking", "beat a defender", 0.08)
            self._rate(ev["opponent_id"], ev, "defending", "was dribbled past", -0.06)
        else:
            self._rate(pid, ev, "attacking", "lost the ball dribbling", -0.07)
            if ev["x"] < 35:
                self.pending_errors.append({"player": pid, "team": team, "time": self.now, "what": "lost the ball"})

    def _on_shot(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        opp = self.other[team]
        ts, ps = self.team[team], self.players[pid]
        self._touch(pid)
        ts.shots += 1
        ps.shots += 1
        ts.xg += ev["xg"]
        ps.xg += ev["xg"]
        self.patterns.add(self.now, "threat", team, ev["xg"])
        if ev["xg"] >= BIG_CHANCE_XG and ev["kind"] != "penalty":
            ts.big_chances += 1
        on_target = ev["outcome"] in ("goal", "saved")
        if on_target:
            ts.shots_on_target += 1
            ps.shots_on_target += 1
        self._rate(pid, ev, "attacking", "shot", ev["xg"] * 0.6 + (0.05 if on_target else 0.0))

        assister = None
        lp = self.last_pass
        if lp and lp["possession"] == ev.get("possession_id") and lp["receiver"] == pid and lp["passer"] != pid:
            assister = lp["passer"]

        # A giveaway in the opponent's own third that led straight to this shot is an error.
        for err in self.pending_errors:
            if err["team"] == opp and self.now - err["time"] <= ERROR_WINDOW_S:
                label = f"{err['what']}, leading to a {'goal' if ev['outcome'] == 'goal' else 'shot'}"
                self._rate(err["player"], ev, "errors", label, -0.8 if ev["outcome"] == "goal" else -0.25)
        self.pending_errors = []

        if ev["outcome"] == "goal":
            wp_before = dict(self.wp)
            self.score[team] += 1
            ts.goals += 1
            ps.goals += 1
            wp_after = self._win_prob()
            swing = self._team_win(team, wp_after) - self._team_win(team, wp_before)
            self._rate(pid, ev, "goals", "goal", 0.9 + 0.8 * max(0.0, swing))
            if assister:
                self.players[assister].assists += 1
                self.players[assister].key_passes += 1
                self._rate(assister, ev, "goals", "assist", 0.55 + 0.4 * max(0.0, swing))
            gk = next((p for p in self._on_pitch(opp) if p.position == "GK"), None)
            for p in self._on_pitch(opp):
                if p.position == "GK":
                    p.goals_conceded += 1
                    self._rate(p.player_id, ev, "conceding", "goal conceded",
                               -0.05 if ev["kind"] == "penalty" else -0.15 - 0.35 * (1 - ev["xg"]))
                else:
                    self._rate(p.player_id, ev, "conceding", "goal conceded", -0.12)
            self._signal(out, "goal", ev, team, pid,
                         assist_player_id=assister,
                         assist_player_name=self.players[assister].name if assister else None,
                         xg=ev["xg"], kind=ev["kind"], body_part=ev["body_part"],
                         score={self.home: self.score[self.home], self.away: self.score[self.away]},
                         win_prob_before=wp_before, win_prob_after=wp_after, win_prob_swing=round(swing, 3),
                         goalkeeper_id=gk.player_id if gk else None)
            self._goal_milestones(ev, out, team, pid, assister)
        else:
            if assister:
                self.players[assister].key_passes += 1
                self._rate(assister, ev, "attacking", "key pass", 0.12 + ev["xg"] * 0.3)
            if ev["outcome"] == "saved" and ev.get("keeper_id"):
                kp = self.players[ev["keeper_id"]]
                kp.saves += 1
                self._rate(kp.player_id, ev, "goalkeeping", "save", 0.1 + ev["xg"] * 1.0)
            if ev["xg"] >= BIG_CHANCE_XG:
                self._rate(pid, ev, "attacking", "missed a big chance", -0.15)
                self._signal(out, "big_chance_missed", ev, team, pid, xg=ev["xg"], outcome=ev["outcome"],
                             kind=ev["kind"], saved_by=ev.get("keeper_id"))
            elif ev["xg"] < 0.04 and not on_target:
                self._rate(pid, ev, "attacking", "wasteful shot", -0.03)
        self.last_pass = None

    def _on_pressure(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        self.team[team].pressures += 1
        self.players[pid].pressures += 1
        if ev["x"] > HALFWAY_X:
            self.team[team].pressures_high += 1
            self.patterns.add(self.now, "high_pressure", team)
        self._rate(pid, ev, "defending", "pressed", 0.008)

    def _on_tackle(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        ps = self.players[pid]
        ps.tackles += 1
        if ev["outcome"] == "won":
            ps.tackles_won += 1
            self.team[team].tackles_won += 1
            self._rate(pid, ev, "defending", "tackle won", 0.12)
            if ev["x"] > 42:
                self.team[team].defensive_actions_high += 1
        else:
            self._rate(pid, ev, "defending", "missed tackle", -0.07)

    def _on_interception(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        self.players[pid].interceptions += 1
        self.team[team].interceptions += 1
        self._rate(pid, ev, "defending", "interception", 0.1)
        if ev["x"] > 42:
            self.team[team].defensive_actions_high += 1

    def _on_recovery(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        self._touch(pid)
        self.players[pid].recoveries += 1
        self.team[team].recoveries += 1
        self._rate(pid, ev, "goalkeeping" if self.players[pid].position == "GK" else "defending",
                   "won the loose ball", 0.04)

    def _on_clearance(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        self._touch(pid)
        self.players[pid].clearances += 1
        self.team[team].clearances += 1
        self._rate(pid, ev, "defending", "clearance", 0.05)

    def _on_foul(self, ev, out):
        team, pid = ev["team_id"], ev["player_id"]
        ts, ps = self.team[team], self.players[pid]
        ts.fouls += 1
        ps.fouls += 1
        self.players[ev["victim_id"]].fouled += 1
        if ev["x"] > 42:
            ts.defensive_actions_high += 1
        penalty = ev.get("penalty", False)
        self._rate(pid, ev, "discipline", "foul", -0.05)
        self._rate(ev["victim_id"], ev, "attacking", "won a penalty" if penalty else "won a foul", 0.25 if penalty else 0.03)
        if penalty:
            self._rate(pid, ev, "errors", "gave away a penalty", -0.5)
            self._signal(out, "penalty_awarded", ev, self.other[team], ev["victim_id"], fouled_by=pid,
                         fouled_by_name=ps.name)
        if ev["card"] == "yellow":
            ps.yellow = True
            ts.yellows += 1
            self._rate(pid, ev, "discipline", "yellow card", -0.35)
        elif ev["card"] == "red":
            second = ps.yellow
            ps.red = True
            ps.off_at = self.now
            ts.reds += 1
            self.men[team] -= 1
            wp_before = dict(self.wp)
            self._rate(pid, ev, "discipline", "sent off (second yellow)" if second else "red card", -1.5)
            wp_after = self._win_prob()
            self._signal(out, "red_card", ev, team, pid, second_yellow=second, men_left=self.men[team],
                         win_prob_before=wp_before, win_prob_after=wp_after,
                         win_prob_swing=round(self._team_win(team, wp_after) - self._team_win(team, wp_before), 3))

    def _on_substitution(self, ev, out):
        team = ev["team_id"]
        off, on = self.players[ev["player_off_id"]], self.players[ev["player_on_id"]]
        off.off_at = self.now
        on.on_at = self.now
        self.team[team].subs += 1

    def _on_match_state(self, ev, out):
        if ev["state"] == "full_time":
            self.finished = True
            for team in (self.home, self.away):
                if self.score[self.other[team]] == 0:
                    # Everyone who played 60+ minutes earns it, including players substituted late,
                    # but not a player who was sent off.
                    played = [p for p in self.players.values() if p.team_id == team and p.on_at is not None and not p.red]
                    for p in played:
                        if p.minutes(self.now) >= 60 and p.position in ("GK", "CB", "FB"):
                            bonus = 0.35 if p.position == "GK" else 0.2
                            self._rate(p.player_id, ev, "goalkeeping" if p.position == "GK" else "defending",
                                       "clean sheet", bonus)
                            if p.position == "GK":
                                n = self.history[p.player_id]["season_clean_sheets"] + 1
                                if n in (1, 5, 10, 15):
                                    self._signal(out, "milestone", ev, team, p.player_id,
                                                 milestone="season_clean_sheets", count=n)
            self._run_milestones(ev, out)
            potm = max((p for p in self.players.values() if p.on_at is not None),
                       key=lambda p: self.ratings.rating(p.player_id, p.minutes(self.now)))
            self._signal(out, "full_time", ev, None, potm.player_id,
                         score={self.home: self.score[self.home], self.away: self.score[self.away]},
                         player_of_the_match_rating=self.ratings.rating(potm.player_id, potm.minutes(self.now)))
        elif ev["state"] == "half_time":
            self._signal(out, "half_time", ev, score={self.home: self.score[self.home], self.away: self.score[self.away]})

    # ------------------------------------------------------------ milestones

    def _goal_milestones(self, ev, out, team, pid, assister):
        ps, hist = self.players[pid], self.history[pid]
        if ps.goals == 2:
            self._signal(out, "milestone", ev, team, pid, milestone="brace", count=2)
        elif ps.goals == 3:
            self._signal(out, "milestone", ev, team, pid, milestone="hat_trick", count=3)
        season = hist["season_goals"] + ps.goals
        if season in SEASON_GOAL_MILESTONES:
            self._signal(out, "milestone", ev, team, pid, milestone="season_goals", count=season,
                         first_of_season=season == 1)
        career = hist["club_career_goals"] + ps.goals
        if career in CAREER_GOAL_MILESTONES:
            self._signal(out, "milestone", ev, team, pid, milestone="club_career_goals", count=career)
        if assister:
            n = self.history[assister]["season_assists"] + self.players[assister].assists
            if n in SEASON_ASSIST_MILESTONES:
                self._signal(out, "milestone", ev, team, assister, milestone="season_assists", count=n)

    def _run_milestones(self, ev, out):
        """Team runs that this result extends or ends (from the last five results in match_meta)."""
        def streak(last5, test):
            n = 0
            for r in reversed(last5):
                if not test(r):
                    break
                n += 1
            return n

        for team in (self.home, self.away):
            last5 = self.meta[self.side[team]]["history"]["last5"]
            mine, theirs = self.score[team], self.score[self.other[team]]
            result = "W" if mine > theirs else "D" if mine == theirs else "L"
            wins = streak(last5, lambda r: r == "W")
            losses = streak(last5, lambda r: r == "L")
            unbeaten = streak(last5, lambda r: r != "L")
            if result == "W" and wins >= 2:
                self._signal(out, "milestone", ev, team, milestone="winning_run", count=wins + 1)
            if result != "L" and unbeaten >= 3:
                self._signal(out, "milestone", ev, team, milestone="unbeaten_run", count=unbeaten + 1)
            if result == "L" and losses >= 2:
                self._signal(out, "milestone", ev, team, milestone="losing_run", count=losses + 1)
            if result == "L" and unbeaten >= 3:
                self._signal(out, "milestone", ev, team, milestone="unbeaten_run_ended", count=unbeaten)
            if result != "L" and losses >= 2:
                self._signal(out, "milestone", ev, team, milestone="losing_run_ended", count=losses)

    # ------------------------------------------------------------ rating and pattern signals

    def _check_ratings(self, ev, out):
        # Every player whose points changed on this event: the scorer, but also the assister,
        # conceding defenders, a player whose earlier giveaway led to this shot, and so on.
        for pid in sorted(self.ratings.pop_changed()):
            p = self.players.get(pid)
            if not p or p.on_at is None:
                continue
            mins = p.minutes(self.now)
            r = self.ratings.rating(pid, mins)
            hist = self._rating_hist[pid]
            hist.append((self.now, r))
            while hist and hist[0][0] < self.now - 600:
                hist.popleft()
            if mins >= 15 and len(hist) > 1:
                low = min(v for _, v in hist)
                high = max(v for _, v in hist)
                if r - low >= 0.7:
                    self._signal(out, "rating_jump", ev, p.team_id, pid, cooldown_key=("rating_jump", pid),
                                 cooldown_s=600, rating=r, from_rating=low, change=round(r - low, 1),
                                 reasons=self.ratings.breakdown(pid, mins, top=3)["key_moments"])
                elif high - r >= 0.7:
                    self._signal(out, "rating_drop", ev, p.team_id, pid, cooldown_key=("rating_drop", pid),
                                 cooldown_s=600, rating=r, from_rating=high, change=round(r - high, 1),
                                 reasons=self.ratings.breakdown(pid, mins, top=3)["key_moments"])
            for mark in (8.0, 9.0):
                if r >= mark and mark not in self._rating_marks[pid] and mins >= 20:
                    self._rating_marks[pid].add(mark)
                    self._signal(out, "rating_milestone", ev, p.team_id, pid, rating=r, threshold=mark)

    def _check_patterns(self, ev, out):
        minute = int(self.now // 60)
        if minute == self._last_minute_checked or self.now < 300:
            return
        self._last_minute_checked = minute
        cur = self.patterns.current()
        m = self.patterns.momentum
        self._momentum_extreme.append((self.now, m))
        while self._momentum_extreme and self._momentum_extreme[0][0] < self.now - 600:
            self._momentum_extreme.popleft()
        lo = min(v for _, v in self._momentum_extreme)
        hi = max(v for _, v in self._momentum_extreme)
        if m >= 0.4 and lo <= -0.4:
            self._signal(out, "momentum_swing", ev, self.home, cooldown_key=("swing",), cooldown_s=600,
                         momentum=round(m, 2), from_momentum=round(lo, 2), towards=self.home)
        elif m <= -0.4 and hi >= 0.4:
            self._signal(out, "momentum_swing", ev, self.away, cooldown_key=("swing",), cooldown_s=600,
                         momentum=round(m, 2), from_momentum=round(hi, 2), towards=self.away)
        if abs(m) >= 0.7:
            team = self.home if m > 0 else self.away
            self._signal(out, "dominance", ev, team, cooldown_key=("dominance", team), cooldown_s=900,
                         momentum=round(m, 2), field_tilt=cur["field_tilt"][team])
        for team in (self.home, self.away):
            rate = cur["pressure"][team]
            avg = self.team[team].pressures_high / max(1.0, self.now / 60)
            if rate >= 2.0 and rate >= 1.6 * avg:
                self._signal(out, "pressing_spell", ev, team, cooldown_key=("press", team), cooldown_s=600,
                             high_pressures_per_min=rate, match_average=round(avg, 2))
        if cur["chaos"] >= 0.75:
            self._signal(out, "chaos_spike", ev, None, cooldown_key=("chaos",), cooldown_s=600,
                         chaos=cur["chaos"], possession_changes_per_min=cur["possession_changes_per_min"])

    # ------------------------------------------------------------ output

    def snapshot(self, top_moments: int = 5) -> dict:
        teams = {}
        for team in (self.home, self.away):
            teams[team] = self.team[team].summary(self.team[self.other[team]])
            teams[team]["men"] = self.men[team]
        players = {}
        for pid, p in self.players.items():
            if p.on_at is None:
                continue
            mins = p.minutes(self.now)
            d = p.summary(self.now)
            d["on_pitch"] = p.off_at is None
            d.update(self.ratings.breakdown(pid, mins, top=top_moments))
            players[pid] = d
        return {
            "match_id": self.meta["match"]["id"],
            "seq": self.seq,
            "clock": self.clock,
            "period": self.period,
            "match_minute": round(self.match_minute, 2),
            "finished": self.finished,
            "score": dict(self.score),
            "win_probability": self.wp,
            "teams": teams,
            "patterns": self.patterns.current(),
            "momentum_series": list(self.patterns.momentum_series),
            "players": players,
        }
