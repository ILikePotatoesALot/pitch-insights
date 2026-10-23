"""Personalise: what the viewer's profile does to the Director's cues.

A viewer sets a profile (mode, favourite club, favourite player, focus metric; the language is handled by the
server's `lang`). It arrives as query parameters on the WebSocket and is checked against the match, so a bad or
unknown value is ignored rather than trusted. Then, for every cue the CueBuilder makes:

- **Boost.** Cues about the favourite player gain `player_boost` priority and cues about the favourite club
  `team_boost`, never past the urgent line (a boost can't turn a story cue into a goal-style one that skips
  cooldowns), and each carries `why` ("favourite_player" or "favourite_club") so the app can say why it is there.
- **Alerts.** A goal, an assist, a red or yellow card, or a rating jump, drop or milestone by the favourite
  player becomes a `fan_alert` cue made for everyone (casual fans included). It replaces the generic player tag
  or rating alert for the same moment, so the favourite isn't announced twice.
- **Relevance.** A viewer with a favourite side doesn't spend a slot, a cooldown or the card limit on a rating
  alert or speed popup about a player of the other side. Everything urgent, every goal, red card and summary,
  and everything about the favourite always gets through.
- **Focus metric.** A stat card shows the viewer's focus metric as its first row (marked `focus`).

It is deterministic code, not a model call: the same profile over the same match gives the same cues (see
`cue_sheet`). The only things it stores or sends are the profile choices themselves; no name, id or history.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pitch_insights.director.cues import DURATION, CueBuilder, cue
from pitch_insights.director.scheduler import DEFAULT_RULES

MODES = ("casual", "analyst")
DEFAULT_MODE = "analyst"  # what the server assumed before profiles existed
# The metric a viewer can follow most closely: the key is the one the team stats and stat-card rows use.
FOCUS_METRICS = ("win_probability", "xt_added", "xg", "pass_accuracy_pct", "possession_pct", "shots")
MAX_PARAM = 40  # no value in a profile is longer than a player id; anything longer is junk


@dataclass(frozen=True)
class Profile:
    mode: str = DEFAULT_MODE
    team_id: str | None = None
    player_id: str | None = None
    focus: str | None = None

    def public(self) -> dict:
        """What is sent back to the browser: the choices as the server applied them."""
        return {"mode": self.mode, "team_id": self.team_id, "player_id": self.player_id, "focus": self.focus}


def parse_profile(params: Mapping[str, str], meta: dict) -> Profile:
    """The viewer's profile from query parameters (`mode`, `team`, `player`, `focus`), checked against this match.

    Anything missing, malformed, too long or not in this match (a club that isn't playing, a player nobody
    plays) is ignored and leaves that choice at its default; it never raises."""
    def clean(key: str, fold) -> str | None:
        v = params.get(key)
        if not isinstance(v, str):
            return None
        v = v.strip()
        return fold(v) if 0 < len(v) <= MAX_PARAM else None

    teams = {meta["home"]["id"], meta["away"]["id"]}
    players = {p["id"] for t in ("home", "away") for p in meta[t]["players"]}
    mode, team = clean("mode", str.lower), clean("team", str.upper)
    player, focus = clean("player", str.upper), clean("focus", str.lower)
    return Profile(mode=mode if mode in MODES else DEFAULT_MODE, team_id=team if team in teams else None,
                   player_id=player if player in players else None, focus=focus if focus in FOCUS_METRICS else None)


@dataclass(frozen=True)
class PersonaliseRules:
    player_boost: int = 20
    team_boost: int = 10
    # Priorities of the favourite's alerts. A goal or red card is urgent, like the lower-third beside it.
    alert_priority: tuple[tuple[str, int], ...] = (
        ("goal", 92), ("red_card", 90), ("assist", 82), ("yellow_card", 70),
        ("rating_up", 65), ("rating_down", 65), ("rating_milestone", 65))
    # Cards about a player of the other side, which a fan of this side can do without.
    skippable: tuple[str, ...] = ("rating_alert", "speed_popup")


DEFAULT_PERSONALISE = PersonaliseRules()
RATING_ALERTS = {"rating_jump": "rating_up", "rating_drop": "rating_down", "rating_milestone": "rating_milestone"}


class Personaliser:
    """Applies one viewer's profile to the Director's cues for one match. With no favourites and no focus it
    changes nothing, so a viewer without a profile sees exactly what they did before profiles existed."""

    def __init__(self, profile: Profile, meta: dict, rules: PersonaliseRules = DEFAULT_PERSONALISE):
        self.profile, self.rules = profile, rules
        self.home, self.away = meta["home"]["id"], meta["away"]["id"]
        self._people = {p["id"]: p | {"team_id": t["id"]} for t in (meta["home"], meta["away"]) for p in t["players"]}
        fav = self._people.get(profile.player_id or "")
        # Their side: the chosen club, or the club of the chosen player.
        self.side = profile.team_id or (fav["team_id"] if fav else None)
        self._priority = dict(rules.alert_priority)

    @property
    def active(self) -> bool:
        return bool(self.profile.team_id or self.profile.player_id or self.profile.focus)

    # ------------------------------------------------------------ the pipeline the server and cue_sheet share

    def cues(self, builder: CueBuilder, ev: dict, moments: list[dict], state: dict | None,
             state_fn: Callable[[], dict], match_time: float) -> list[dict]:
        """Every cue this viewer's screen is offered for one event: the moments' cues (with the live state for
        stats), then the favourite's alerts, personalised. `state` is the live state if the caller already has it;
        otherwise `state_fn` makes it when something needs it (a yellow card makes no moment, but needs a rating)."""
        alerts = [a for m in moments if (a := self._moment_alert(m, state))] if self.profile.player_id else []
        event_alert = self._event_alert(ev, match_time)
        if event_alert:
            alerts.append(self._fill(event_alert, state if state is not None else state_fn()))
        # The favourite's own goal, red card or rating change replaces the generic tag or alert for that moment.
        replaced = {a["moment_id"] for a in alerts if a["data"]["event"] != "assist"}
        out: list[dict] = []
        for m in moments:
            out += [c for c in builder.for_moment(m, state)
                    if not (c["moment_id"] in replaced and c["about"]["player_id"] == self.profile.player_id
                            and c["template"] in ("player_tag", "rating_alert"))]
        out += alerts
        return [c for c in (self.adjust(c, state) for c in out) if c]

    # ------------------------------------------------------------ boost, relevance, focus

    def adjust(self, c: dict, state: dict | None) -> dict | None:
        """The cue as this viewer should get it, or None if it isn't for them. Never changes the cue it is given."""
        about, urgent = c["about"], DEFAULT_RULES.urgent
        fav_player = bool(self.profile.player_id) and about["player_id"] == self.profile.player_id
        fav_side = bool(self.side) and about["team_id"] == self.side
        if (self.side and not fav_player and c["priority"] < urgent and c["template"] in self.rules.skippable
                and about["player_id"] and about["team_id"] not in (None, self.side)):
            return None
        out = dict(c)
        if fav_player or fav_side:
            boost = self.rules.player_boost if fav_player else self.rules.team_boost
            out["priority"] = c["priority"] if c["priority"] >= urgent else min(urgent - 1, c["priority"] + boost)
            out["why"] = "favourite_player" if fav_player else "favourite_club"
        if c["template"] == "stat_card" and self.profile.focus and state:
            out["data"] = self._with_focus(c["data"], state)
        return out

    def _with_focus(self, data: dict, state: dict) -> dict:
        key = self.profile.focus
        row = next((r for r in data["rows"] if r["key"] == key), None) or self._row(key, state)
        if not row:
            return data
        return data | {"rows": [row | {"focus": True}] + [r for r in data["rows"] if r["key"] != key]}

    def _row(self, key: str, state: dict) -> dict | None:
        if key == "win_probability":
            wp = state.get("win_probability")
            return {"key": key, "home": round(wp["home"] * 100), "away": round(wp["away"] * 100)} if wp else None
        h, a = state["teams"][self.home].get(key), state["teams"][self.away].get(key)
        if h is None or a is None:
            return None
        f = (lambda v: round(v, 2)) if key in ("xg", "xt_added") else (lambda v: v)
        return {"key": key, "home": f(h), "away": f(a)}

    # ------------------------------------------------------------ the favourite's alerts

    def _alert(self, event: str, time: float, clock: str, moment_id: str | None, pid: str, state: dict | None,
               **extra) -> dict:
        person = self._people[pid]
        c = cue("fan_alert", time, DURATION["fan_alert"], self._priority[event], tier="notable", detail="casual",
                moment_id=moment_id, team_id=person["team_id"], player_id=pid,
                data={"event": event, "clock": clock, "name": person["name"], "number": person["number"],
                      "position": person["position"], "rating": None, "goals": None, "assists": None} | extra)
        c["topic"] = None  # the favourite's alerts are spaced by the template's cooldown; urgent ones need no spacing
        c["why"] = "favourite_player"
        return self._fill(c, state)

    @staticmethod
    def _fill(c: dict, state: dict | None) -> dict:
        """Their live rating and tally, from the state as it is when the alert starts."""
        p = next((p for p in (state or {}).get("players", []) if p["player_id"] == c["about"]["player_id"]), None)
        if p:
            c["data"] |= {"rating": p["rating"], "goals": p["goals"], "assists": p["assists"]}
        return c

    def _moment_alert(self, m: dict, state: dict | None) -> dict | None:
        fav, mtype = self.profile.player_id, m["type"]
        if mtype == "goal" and m.get("player_id") == fav:
            return self._alert("goal", m["match_time"], m["clock"], m["id"], fav, state)
        if mtype == "goal" and any(f["kind"] == "assist" and f.get("value") == fav for f in m["facts"]):
            return self._alert("assist", m["match_time"], m["clock"], m["id"], fav, state)
        if mtype == "red_card" and m.get("player_id") == fav:
            return self._alert("red_card", m["match_time"], m["clock"], m["id"], fav, state)
        if mtype in RATING_ALERTS and m.get("player_id") == fav:
            change = next((f["value"] for f in m["facts"] if f["kind"] == "rating_change"), None)
            return self._alert(RATING_ALERTS[mtype], m["match_time"], m["clock"], m["id"], fav, state, change=change)
        return None

    def _event_alert(self, ev: dict, match_time: float) -> dict | None:
        """A booking is no moment, so it comes from the event itself (a red card is a moment, and handled there)."""
        fav = self.profile.player_id
        if fav and ev["type"] == "foul" and ev.get("card") == "yellow" and ev.get("player_id") == fav:
            return self._alert("yellow_card", match_time, ev["clock"], None, fav, None)
        return None
