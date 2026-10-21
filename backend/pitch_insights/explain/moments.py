"""The Moment Scorer: turns the Interpreter's signals into ranked moments with evidence.

It runs live, so it decides how big a moment is when it happens, using only what
is known at that point. For each event it:

1. groups that event's signals into moments (a goal, the scorer's brace and his
   rating jump become one moment, not three);
2. scores each moment from 0 to 1 and puts it in a tier: headline, notable or minor;
3. builds an evidence pack: plain facts with the numbers behind them. The Explainer
   agent may only use these facts, and the fallback headline means the app still
   works without a language model.

    brain = MatchBrain(meta)
    for ev in events:
        out = brain.update(ev)   # {"event", "signals", "moments"}
"""

from __future__ import annotations

from collections import deque

from pitch_insights.interpret.interpreter import Interpreter

HEADLINE, NOTABLE = 0.6, 0.35
WINDOW_S = 300.0

# Signals that anchor a moment; other signals from the same event attach to them.
ANCHORS = ("goal", "red_card", "penalty_awarded", "big_chance_missed", "full_time", "half_time")
PATTERN_TYPES = ("momentum_swing", "dominance", "pressing_spell", "chaos_spike")


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def pct(p: float) -> str:
    return f"{round(p * 100)}%"


def tier(importance: float) -> str:
    return "headline" if importance >= HEADLINE else "notable" if importance >= NOTABLE else "minor"


class MomentScorer:
    def __init__(self, interp: Interpreter):
        self.i = interp
        meta = interp.meta
        self.short = {meta[s]["id"]: meta[s]["short_name"] for s in ("home", "away")}
        self.recent: deque[tuple[float, str, str, float]] = deque()  # (time, team, kind, value)
        self.moments: list[dict] = []
        self._score_before = {interp.home: 0, interp.away: 0}

    # ------------------------------------------------------------ helpers

    def _surname(self, pid: str | None) -> str:
        return self.i.players[pid].name.split()[-1] if pid else ""

    def _team_name(self, team: str | None) -> str:
        return self.short.get(team, "")

    def _score_text(self, score: dict | None = None) -> str:
        s = score or self.i.score
        return f"{self._team_name(self.i.home)} {s[self.i.home]}–{s[self.i.away]} {self._team_name(self.i.away)}"

    def _win(self, team: str, wp: dict) -> float:
        return wp[self.i.side[team]]

    def _recent_counts(self, team: str) -> dict:
        shots = sum(1 for _, t, k, _ in self.recent if t == team and k == "shot")
        xg = sum(v for _, t, k, v in self.recent if t == team and k == "shot")
        corners = sum(1 for _, t, k, _ in self.recent if t == team and k == "corner")
        return {"shots": shots, "xg": round(xg, 2), "corners": corners}

    def _track(self, ev: dict):
        now = self.i.now
        team = ev.get("team_id")
        if ev["type"] == "shot":
            self.recent.append((now, team, "shot", ev["xg"]))
        elif ev["type"] == "pass" and ev["kind"] == "corner":
            self.recent.append((now, team, "corner", 1.0))
        while self.recent and self.recent[0][0] < now - WINDOW_S:
            self.recent.popleft()

    # ------------------------------------------------------------ facts

    def _context_facts(self, team: str) -> list[dict]:
        """What the last five minutes looked like from `team`'s point of view."""
        facts = []
        p = self.i.patterns.current()
        m = p["momentum"] * (1 if team == self.i.home else -1)
        if abs(m) >= 0.3:
            facts.append({"kind": "momentum", "value": round(m, 2),
                          "text": f"{self._team_name(team)} {'had the upper hand' if m > 0 else 'were under pressure'} "
                                  f"in the last five minutes (momentum {m:+.2f} from their side)."})
        tilt = p["field_tilt"][team]
        if tilt >= 0.65 or tilt <= 0.35:
            facts.append({"kind": "field_tilt", "value": tilt,
                          "text": f"{self._team_name(team)} played {pct(tilt)} of the final-third passes in the last five minutes."})
        rc = self._recent_counts(team)
        if rc["shots"] >= 3:
            facts.append({"kind": "recent_shots", "value": rc,
                          "text": f"{self._team_name(team)} had {rc['shots']} shots (xG {rc['xg']}) and {rc['corners']} "
                                  f"corner{'' if rc['corners'] == 1 else 's'} in the last five minutes."})
        return facts

    def _rating_fact(self, pid: str) -> dict:
        p = self.i.players[pid]
        r = self.i.ratings.rating(pid, p.minutes(self.i.now))
        return {"kind": "rating", "value": r, "player_id": pid,
                "text": f"{self._surname(pid)}'s live rating is {r}."}

    def _totals_fact(self) -> dict:
        h, a = self.i.home, self.i.away
        th, ta = self.i.team[h], self.i.team[a]
        return {"kind": "match_totals",
                "value": {h: {"shots": th.shots, "xg": round(th.xg, 2)}, a: {"shots": ta.shots, "xg": round(ta.xg, 2)}},
                "text": f"Shots so far: {self._team_name(h)} {th.shots} (xG {th.xg:.2f}), "
                        f"{self._team_name(a)} {ta.shots} (xG {ta.xg:.2f})."}

    # ------------------------------------------------------------ per-type builders

    def _goal(self, s: dict) -> tuple[float, str, list[dict]]:
        d, team, pid = s["data"], s["team_id"], s["player_id"]
        opp = self.i.other[team]
        before = self._score_before
        mine_b, theirs_b = before[team], before[opp]
        mine, theirs = d["score"][team], d["score"][opp]
        who, tname, minute = self._surname(pid), self._team_name(team), s["minute"]
        spot = " from the spot" if d["kind"] == "penalty" else ""
        if mine_b == 0 and theirs_b == 0:
            headline = f"{who} opens the scoring{spot}"
        elif mine == theirs:
            headline = f"{who} equalises for {tname}{spot}"
        elif mine_b <= theirs_b and mine > theirs:
            headline = f"{who} puts {tname} ahead{' late' if minute >= 85 else ''}{spot}"
        elif mine < theirs:
            headline = f"{who} pulls one back for {tname}{spot}"
        else:
            headline = f"{who} makes it {mine}–{theirs} to {tname}{spot}"

        w_before, w_after = self._win(team, d["win_prob_before"]), self._win(team, d["win_prob_after"])
        facts = [
            {"kind": "score", "value": d["score"], "text": f"It's now {self._score_text(d['score'])}."},
            {"kind": "win_probability", "value": {"before": w_before, "after": w_after},
             "text": f"{tname}'s chance of winning went from {pct(w_before)} to {pct(w_after)}."},
        ]
        if d.get("assist_player_id"):
            facts.append({"kind": "assist", "value": d["assist_player_id"],
                          "text": f"Assisted by {self._surname(d['assist_player_id'])}."})
        xg = d["xg"]
        if d["kind"] == "penalty":
            facts.append({"kind": "chance", "value": xg, "text": "A penalty (xG 0.78)."})
        elif xg >= 0.3:
            facts.append({"kind": "chance", "value": xg, "text": f"A big chance, xG {xg:.2f}."})
        elif xg < 0.1:
            facts.append({"kind": "chance", "value": xg,
                          "text": f"An unlikely finish: xG {xg:.2f}, so about {round(xg * 100)} in 100 shots like it go in."})
        else:
            facts.append({"kind": "chance", "value": xg, "text": f"Chance quality xG {xg:.2f}."})
        if d["body_part"] == "head":
            facts.append({"kind": "technique", "value": "head", "text": "Scored with a header."})
        goals_now = self.i.players[pid].goals
        if goals_now >= 2:
            facts.append({"kind": "match_goals", "value": goals_now, "text": f"His {ordinal(goals_now)} goal of the match."})
        hist = self.i.history[pid]
        season = hist["season_goals"] + goals_now
        facts.append({"kind": "season_goals", "value": season,
                      "text": "His first goal of the season." if season == 1 else f"His {ordinal(season)} goal of the season."})
        m = self.i.patterns.current()["momentum"] * (1 if team == self.i.home else -1)
        if m <= -0.3:
            facts.append({"kind": "run_of_play", "value": round(m, 2),
                          "text": f"Against the run of play: {self._team_name(opp)} had been on top."})
        facts += self._context_facts(team)
        facts.append(self._rating_fact(pid))
        facts.append(self._totals_fact())

        swing = abs(w_after - w_before)
        imp = 0.6 + 0.4 * min(1.0, swing / 0.5)
        if minute >= 80:
            imp += 0.08
        return imp, headline, facts

    def _red_card(self, s):
        d, team, pid = s["data"], s["team_id"], s["player_id"]
        w_b, w_a = self._win(team, d["win_prob_before"]), self._win(team, d["win_prob_after"])
        why = "a second yellow card" if d["second_yellow"] else "a straight red card"
        facts = [
            {"kind": "card", "value": "second_yellow" if d["second_yellow"] else "red",
             "text": f"{self._surname(pid)} is sent off for {why}."},
            {"kind": "men", "value": d["men_left"], "text": f"{self._team_name(team)} are down to {d['men_left']}."},
            {"kind": "win_probability", "value": {"before": w_b, "after": w_a},
             "text": f"{self._team_name(team)}'s chance of winning dropped from {pct(w_b)} to {pct(w_a)}."},
            {"kind": "score", "value": dict(self.i.score), "text": f"The score is {self._score_text()}."},
            self._rating_fact(pid),
        ]
        imp = 0.55 + 0.4 * min(1.0, abs(w_a - w_b) / 0.3)
        return imp, f"{self._surname(pid)} sent off; {self._team_name(team)} down to {d['men_left']}", facts

    def _penalty(self, s):
        team, pid = s["team_id"], s["player_id"]
        d = s["data"]
        facts = [
            {"kind": "foul", "value": d["fouled_by"],
             "text": f"{self._surname(d['fouled_by'])} fouled {self._surname(pid)} in the box."},
            {"kind": "score", "value": dict(self.i.score), "text": f"The score is {self._score_text()}."},
            {"kind": "chance", "value": 0.78, "text": "Penalties are scored about 78% of the time."},
        ]
        return 0.45, f"Penalty to {self._team_name(team)}", facts

    def _big_chance(self, s):
        d, team, pid = s["data"], s["team_id"], s["player_id"]
        result = {"saved": "saved", "off_target": "off target", "blocked": "blocked", "woodwork": "off the woodwork"}[d["outcome"]]
        facts = [{"kind": "chance", "value": d["xg"],
                  "text": f"{self._surname(pid)}'s shot was {result}: xG {d['xg']:.2f}, so it goes in about "
                          f"{round(d['xg'] * 100)} times in 100."}]
        if d.get("saved_by"):
            facts.append({"kind": "save", "value": d["saved_by"], "text": f"Saved by {self._surname(d['saved_by'])}."})
        facts.append({"kind": "score", "value": dict(self.i.score), "text": f"The score is {self._score_text()}."})
        facts += self._context_facts(team)
        close = abs(self.i.score[team] - self.i.score[self.i.other[team]]) <= 1
        imp = 0.3 + 0.35 * d["xg"] + (0.08 if close else 0) + (0.06 if s["minute"] >= 75 else 0)
        if d["kind"] == "penalty":
            headline = f"{self._surname(pid)}'s penalty is saved" if d["outcome"] == "saved" else f"{self._surname(pid)} misses a penalty"
            return imp + 0.15, headline, facts
        verb = "misses" if d["outcome"] != "saved" else "is denied"
        return imp, f"{self._surname(pid)} {verb} a big chance", facts

    def _pattern(self, s):
        d, team, kind = s["data"], s.get("team_id"), s["type"]
        facts = self._context_facts(team) if team else []
        if kind == "momentum_swing":
            facts.insert(0, {"kind": "momentum_swing", "value": {"from": d["from_momentum"], "to": d["momentum"]},
                             "text": f"Momentum swung from {d['from_momentum']:+.2f} to {d['momentum']:+.2f} "
                                     f"(positive means {self._team_name(self.i.home)} on top) within ten minutes."})
            imp = 0.34 + 0.15 * min(1.0, max(0.0, abs(d["momentum"] - d["from_momentum"]) - 0.8) / 0.8)
            headline = f"{self._team_name(team)} take control"
        elif kind == "dominance":
            facts.insert(0, {"kind": "dominance", "value": d["momentum"],
                             "text": f"Momentum is {d['momentum']:+.2f}, about as one-sided as it gets "
                                     f"(positive means {self._team_name(self.i.home)} on top)."})
            imp, headline = 0.33, f"{self._team_name(team)} on top"
        elif kind == "pressing_spell":
            facts.insert(0, {"kind": "pressing", "value": d,
                             "text": f"{self._team_name(team)} are making {d['high_pressures_per_min']} high pressures a minute, "
                                     f"against {d['match_average']} on average this match."})
            imp = 0.3 + 0.05 * min(2.0, d["high_pressures_per_min"] - 2)
            headline = f"{self._team_name(team)} turn up the press"
        else:
            facts.insert(0, {"kind": "chaos", "value": d,
                             "text": f"Possession is changing hands {d['possession_changes_per_min']} times a minute."})
            imp, headline = 0.22, "End-to-end spell"
        if kind != "chaos_spike":
            facts.append({"kind": "score", "value": dict(self.i.score), "text": f"The score is {self._score_text()}."})
        return imp, headline, facts

    def _rating(self, s):
        d, pid = s["data"], s["player_id"]
        who = self._surname(pid)
        facts = [self._rating_fact(pid)]
        for r in d.get("reasons", [])[:3]:
            facts.append({"kind": "rating_reason", "value": r["delta"], "text": f"{r['clock']} {r['label']} ({r['delta']:+.2f})."})
        if s["type"] == "rating_jump":
            facts.insert(1, {"kind": "rating_change", "value": d["change"],
                             "text": f"Up from {d['from_rating']} in the last ten minutes."})
            return 0.15 + 0.08 * d["change"], f"{who} growing into the game", facts
        if s["type"] == "rating_drop":
            facts.insert(1, {"kind": "rating_change", "value": d["change"],
                             "text": f"Down from {d['from_rating']} in the last ten minutes."})
            return 0.15 + 0.05 * abs(d["change"]), f"Tough spell for {who}", facts
        imp = 0.45 if d["threshold"] >= 9.0 else 0.33
        article = "an" if str(d["rating"]).startswith("8") else "a"
        return imp, f"{who} hits {article} {d['rating']} rating", facts

    def _milestone(self, s):
        d, pid, team = s["data"], s.get("player_id"), s.get("team_id")
        who, tname, m, n = self._surname(pid), self._team_name(team), d["milestone"], d.get("count")
        table = {
            "hat_trick": (0.5, f"Hat-trick for {who}!", f"{who} has scored three goals in this match."),
            "brace": (0.2, f"Two for {who}", f"{who} has scored twice in this match."),
            "season_goals": (0.25 if n in (1, 10, 20, 30) else 0.18,
                             f"{who}'s {'first goal of the season' if n == 1 else ordinal(n) + ' of the season'}",
                             f"That's {who}'s {ordinal(n)} league goal this season."),
            "club_career_goals": (0.3, f"{n} goals for {tname} for {who}", f"{who} now has {n} goals for {tname}."),
            "season_assists": (0.15, f"{who}'s {ordinal(n)} assist of the season", f"{who} has {n} assists this season."),
            "season_clean_sheets": (0.18, f"{who}'s {ordinal(n)} clean sheet", f"{who} has {n} clean sheets this season."),
            "winning_run": (0.28, f"{tname} make it {n} wins in a row", f"{tname} have won {n} league matches in a row."),
            "unbeaten_run": (0.22, f"{tname} unbeaten in {n}", f"{tname} are unbeaten in {n} league matches."),
            "losing_run": (0.25, f"{n} defeats in a row for {tname}", f"{tname} have lost {n} league matches in a row."),
            "unbeaten_run_ended": (0.3, f"{tname}'s unbeaten run is over", f"{tname} had been unbeaten in {n}."),
            "losing_run_ended": (0.28, f"{tname} end their losing run", f"{tname} had lost {n} in a row."),
        }
        imp, headline, text = table.get(m, (0.15, m.replace("_", " "), m.replace("_", " ")))
        return imp, headline, [{"kind": "milestone", "value": {"milestone": m, "count": n}, "text": text}]

    def _summary(self, s):
        d = s["data"]
        h, a = self.i.home, self.i.away
        snap_teams = {t: self.i.team[t].summary(self.i.team[self.i.other[t]]) for t in (h, a)}
        full = s["type"] == "full_time"
        facts = [{"kind": "score", "value": d["score"], "text": f"{'Full' if full else 'Half'}-time: {self._score_text(d['score'])}."},
                 self._totals_fact(),
                 {"kind": "possession", "value": {t: snap_teams[t]["possession_pct"] for t in (h, a)},
                  "text": f"Possession: {self._team_name(h)} {snap_teams[h]['possession_pct']}%, "
                          f"{self._team_name(a)} {snap_teams[a]['possession_pct']}%."}]
        if full and s.get("player_id"):
            facts.append({"kind": "player_of_the_match", "value": s["player_id"],
                          "text": f"Player of the match: {self.i.players[s['player_id']].name} "
                                  f"({d['player_of_the_match_rating']})."})
        top = sorted((m for m in self.moments if m["tier"] == "headline"), key=lambda m: -m["importance"])[:3]
        for m in top:
            facts.append({"kind": "key_moment", "value": m["id"], "text": f"{m['clock']} {m['headline']}."})
        return (0.9 if full else 0.5), facts[0]["text"].rstrip("."), facts

    # ------------------------------------------------------------ main

    BUILDERS = {
        "goal": "_goal", "red_card": "_red_card", "penalty_awarded": "_penalty", "big_chance_missed": "_big_chance",
        "momentum_swing": "_pattern", "dominance": "_pattern", "pressing_spell": "_pattern", "chaos_spike": "_pattern",
        "rating_jump": "_rating", "rating_drop": "_rating", "rating_milestone": "_rating",
        "milestone": "_milestone", "half_time": "_summary", "full_time": "_summary",
    }

    def update(self, ev: dict, signals: list[dict]) -> list[dict]:
        self._track(ev)
        if not signals:
            self._score_before = dict(self.i.score)
            return []
        groups = self._group(signals)
        out = []
        for primary, attached in groups:
            imp, headline, facts = getattr(self, self.BUILDERS[primary["type"]])(primary)
            for extra in attached:
                e_imp, e_head, e_facts = getattr(self, self.BUILDERS[extra["type"]])(extra)
                facts += self._extra_facts(primary, extra, e_facts, facts)
                imp += 0.25 * e_imp if extra["type"] == "milestone" else 0.05 * e_imp
            if primary["type"] not in ("half_time", "full_time"):
                diff = abs(self._score_before[self.i.home] - self._score_before[self.i.away])
                if diff <= 1:
                    imp *= 1.08
                if primary["minute"] >= 75:
                    imp *= 1.05
            imp = round(min(1.0, imp), 3)
            m = {
                "id": f"M-{len(self.moments) + 1}", "seq": primary["seq"], "clock": primary["clock"],
                "minute": primary["minute"], "period": primary["period"], "match_time": primary["match_time"],
                "type": primary["type"], "team_id": primary.get("team_id"), "player_id": primary.get("player_id"),
                "player_name": primary.get("player_name"), "importance": imp, "tier": tier(imp),
                "headline": headline, "facts": facts,
                "signals": [primary["type"]] + [x["type"] for x in attached],
                "score": dict(self.i.score), "win_probability": dict(self.i.wp),
            }
            self.moments.append(m)
            out.append(m)
        self._score_before = dict(self.i.score)
        return out

    @staticmethod
    def _extra_facts(primary: dict, extra: dict, e_facts: list[dict], facts: list[dict]) -> list[dict]:
        """Facts worth adding from an attached signal, without repeating what the moment already says."""
        if extra["type"] == "milestone":
            if primary["type"] == "goal" and extra["data"]["milestone"] in ("brace", "hat_trick", "season_goals"):
                return []  # the goal's own facts already cover match and season goals
            return e_facts
        if extra["type"].startswith("rating"):
            have = {(f["kind"], f.get("player_id")) for f in facts}
            return [f for f in e_facts if f["kind"] == "rating_change"
                    or (f["kind"] == "rating" and (f["kind"], f.get("player_id")) not in have)]
        kinds = {f["kind"] for f in facts}
        return [f for f in e_facts if f["kind"] not in kinds]

    def _group(self, signals: list[dict]) -> list[tuple[dict, list[dict]]]:
        """One moment per anchor signal, with this event's other signals attached to it.

        Without an anchor, pattern signals for the same team merge into one moment, and a
        player's rating signals merge into one moment per player.
        """
        anchors = [s for s in signals if s["type"] in ANCHORS]
        rest = [s for s in signals if s["type"] not in ANCHORS]
        groups: list[tuple[dict, list[dict]]] = []
        if anchors:
            main = anchors[0]
            groups.append((main, [s for s in rest if s["type"] == "milestone" or s.get("player_id") in
                                  (main.get("player_id"), main["data"].get("assist_player_id"))]))
            attached_ids = {id(s) for s in groups[0][1]}
            for a in anchors[1:]:
                groups.append((a, []))
            rest = [s for s in rest if id(s) not in attached_ids]
        by_key: dict[tuple, list[dict]] = {}
        for s in rest:
            if s["type"] in PATTERN_TYPES:
                key = ("pattern", s.get("team_id"))
            elif s["type"].startswith("rating"):
                key = ("rating", s.get("player_id"))
            else:
                key = (s["type"], s.get("player_id"), s.get("team_id"), s["data"].get("milestone"))
            by_key.setdefault(key, []).append(s)
        order = {t: i for i, t in enumerate(("momentum_swing", "dominance", "pressing_spell", "chaos_spike",
                                              "rating_milestone", "rating_jump", "rating_drop", "milestone"))}
        for items in by_key.values():
            items.sort(key=lambda s: order.get(s["type"], 99))
            groups.append((items[0], items[1:]))
        return groups


class MatchBrain:
    """Interpreter plus Moment Scorer: feed events, get signals and moments."""

    def __init__(self, meta: dict):
        self.interp = Interpreter(meta)
        self.scorer = MomentScorer(self.interp)

    def update(self, ev: dict) -> dict:
        signals = self.interp.update(ev)
        moments = self.scorer.update(ev, signals)
        return {"event": ev, "signals": signals, "moments": moments}

    @property
    def moments(self) -> list[dict]:
        return self.scorer.moments
