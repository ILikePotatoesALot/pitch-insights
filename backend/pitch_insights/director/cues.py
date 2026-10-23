"""What the Director would like to show: overlay cues built from moments and the live state.

A cue is plain JSON, which is the contract with the app:

    {"time": 5421.0,          match seconds of what the cue is about
     "duration": 6.0,         seconds on screen, whatever the replay speed
     "priority": 92,          0-100; decides who is dropped, delayed or pre-empted
     "template": "lower_third",  | stat_card | player_tag | rating_alert | speed_popup
     "tier": "headline",      the moment's tier (headline, notable, minor)
     "detail": "casual",      who it is for: "casual" (everyone) or "analyst" (analysts only)
     "about": {"team_id": ..., "player_id": ...},   what a per-viewer filter can match on
     "topic": "rating_alert:CAR-9",   a player's cards on one template, so he isn't announced twice in a row
     "moment_id": "M-12",
     "data": {...}}           what the template shows; text is never set up in a language here

The scheduler adds an `id` (and a `delay`, if the cue waited). Text that comes from commentary is
whatever the moment carries: the server hands over the moment in the viewer's language, so the
cue is too. Labels such as "Possession" belong to the app, and the data holds only numbers and keys.
"""

from __future__ import annotations

TEMPLATES = ("lower_third", "stat_card", "player_tag", "rating_alert", "speed_popup")
CARD_TEMPLATES = tuple(t for t in TEMPLATES if t != "lower_third")

# Moments that are the event itself, against ones that are the story around it.
EVENT_TYPES = ("goal", "red_card", "penalty_awarded", "big_chance_missed", "half_time", "full_time")
KIND = {"goal": "goal", "red_card": "red_card", "penalty_awarded": "penalty", "big_chance_missed": "chance",
        "half_time": "half_time", "full_time": "full_time", "milestone": "milestone",
        "momentum_swing": "momentum", "dominance": "momentum", "pressing_spell": "pressing",
        "chaos_spike": "chaos"}
DURATION = {"stat_card": 8.0, "summary_card": 12.0, "player_tag": 6.0, "rating_alert": 5.0, "speed_popup": 4.0}
STORY_CAP = 70  # story cues never outrank an event's lower-third
URGENT_EVENTS = ("goal", "red_card")  # always urgent (priority 90 and up), whatever their importance


def _words(text: str | None) -> int:
    return len(text.split()) if text else 0


def lower_third_seconds(casual: str | None, analyst: str | None, fact: str | None) -> float:
    """Six seconds, and a quarter of a second for each word past fifteen, up to ten."""
    words = max(_words(casual), _words(analyst), _words(fact))
    return round(min(10.0, 6.0 + 0.25 * max(0, words - 15)), 2)


def cue(template: str, time: float, duration: float, priority: float, *, tier: str, detail: str,
        moment_id: str | None, data: dict, team_id: str | None = None, player_id: str | None = None) -> dict:
    return {"time": time, "duration": duration, "priority": max(0, min(100, round(priority))),
            "template": template, "tier": tier, "detail": detail,
            "about": {"team_id": team_id, "player_id": player_id},
            "topic": f"{template}:{player_id}" if player_id else None,
            "moment_id": moment_id, "data": data}


class CueBuilder:
    """Turns each moment, with the live state, into the cues it deserves."""

    def __init__(self, meta: dict):
        self.home, self.away = meta["home"]["id"], meta["away"]["id"]

    def for_moment(self, m: dict, state: dict | None) -> list[dict]:
        """The cues for one moment (as the viewer sees it), in the order they'd be offered."""
        out: list[dict] = []
        mtype, tier = m["type"], m["tier"]
        if mtype.startswith("rating_"):
            out.append(self._rating_alert(m, state))
            return out
        if tier != "minor":
            out.append(self._lower_third(m))
            out += self._stat_cards(m, state)
        if mtype in ("goal", "red_card") and m.get("player_id"):
            out.append(self._player_tag(m, state))
        return out

    # ------------------------------------------------------------ templates

    def _lower_third(self, m: dict) -> dict:
        c = m.get("commentary")
        ok = c if c and c.get("status") == "ok" else None
        casual, analyst = (ok["casual"], ok["analyst"]) if ok else (None, None)
        fact = m["facts"][1]["text"] if len(m["facts"]) > 1 else None
        priority = 50 + 50 * m["importance"]
        if m["type"] in URGENT_EVENTS:
            priority = max(90, priority)
        elif m["type"] not in EVENT_TYPES:
            priority = min(priority, STORY_CAP)
        return cue("lower_third", m["match_time"], lower_third_seconds(casual, analyst, fact), priority,
                   tier=m["tier"], detail="casual" if m["tier"] == "headline" else "analyst", moment_id=m["id"],
                   team_id=m.get("team_id"), player_id=m.get("player_id"),
                   data={"kind": KIND.get(m["type"], m["type"]), "clock": m["clock"], "headline": m["headline"],
                         "casual": casual, "analyst": analyst, "fact": fact})

    def _stat_cards(self, m: dict, state: dict | None) -> list[dict]:
        if not state:
            return []
        h, a, mtype = state["teams"][self.home], state["teams"][self.away], m["type"]
        pair = lambda key, f=lambda v: v: {"key": key, "home": f(h[key]), "away": f(a[key])}  # noqa: E731
        if mtype in ("half_time", "full_time"):
            kind, duration, detail = "summary", DURATION["summary_card"], "casual"
            rows = [pair("possession_pct"), pair("shots"), pair("shots_on_target"), pair("xg", lambda v: round(v, 2)),
                    pair("pass_accuracy_pct")]
            priority = 90  # urgent: no other card's cooldown (one the viewer may not even see) can hold it back
        elif mtype in ("momentum_swing", "dominance"):
            kind, duration, detail = "control", DURATION["stat_card"], "analyst"
            tilt = state["patterns"]["field_tilt"]
            rows = [{"key": "field_tilt", "home": round(tilt[self.home] * 100), "away": round(tilt[self.away] * 100)},
                    pair("possession_pct"), pair("shots"), pair("xg", lambda v: round(v, 2))]
            priority = 30 + 30 * m["importance"]
        elif mtype == "pressing_spell":
            kind, duration, detail = "pressing", DURATION["stat_card"], "analyst"
            rows = [pair("pressures_high"), pair("tackles_won"), pair("interceptions")]
            if h["ppda"] is not None and a["ppda"] is not None:
                rows.insert(1, pair("ppda"))
            priority = 30 + 30 * m["importance"]
        else:
            return []
        return [cue("stat_card", m["match_time"], duration, priority, tier=m["tier"], detail=detail,
                    moment_id=m["id"], team_id=m.get("team_id"),
                    data={"kind": kind, "clock": m["clock"], "rows": rows})]

    def _player_tag(self, m: dict, state: dict | None) -> dict:
        pid = m["player_id"]
        p = next((p for p in (state or {}).get("players", []) if p["player_id"] == pid), None)
        goal = m["type"] == "goal"
        return cue("player_tag", m["match_time"], DURATION["player_tag"], (45 + 10 * m["importance"]) if goal else 55,
                   tier=m["tier"], detail="casual", moment_id=m["id"], team_id=m.get("team_id"), player_id=pid,
                   data={"event": m["type"], "clock": m["clock"], "name": (p or {}).get("name") or m.get("player_name"),
                         "number": (p or {}).get("number"), "position": (p or {}).get("position"),
                         "rating": (p or {}).get("rating"), "goals": (p or {}).get("goals"),
                         "assists": (p or {}).get("assists")})

    def _rating_alert(self, m: dict, state: dict | None) -> dict:
        pid = m["player_id"]
        p = next((p for p in (state or {}).get("players", []) if p["player_id"] == pid), None)
        fact = lambda kind: next((f["value"] for f in m["facts"] if f["kind"] == kind), None)  # noqa: E731
        rating, change = fact("rating"), fact("rating_change")
        direction = "milestone" if m["type"] == "rating_milestone" else "up" if m["type"] == "rating_jump" else "down"
        return cue("rating_alert", m["match_time"], DURATION["rating_alert"], 20 + 40 * m["importance"],
                   tier=m["tier"], detail="analyst", moment_id=m["id"], team_id=m.get("team_id"), player_id=pid,
                   data={"direction": direction, "clock": m["clock"], "name": (p or {}).get("name") or m.get("player_name"),
                         "number": (p or {}).get("number"), "rating": rating, "change": change})

    @staticmethod
    def speed_popup(time: float, player_id: str, name: str, kmh: float, team_id: str | None = None) -> dict:
        """A top-speed popup. Synthetic matches have no speeds yet; the video path's `frame` messages will."""
        return cue("speed_popup", time, DURATION["speed_popup"], 35, tier="minor", detail="analyst", moment_id=None,
                   team_id=team_id, player_id=player_id, data={"name": name, "speed_kmh": round(kmh, 1)})
