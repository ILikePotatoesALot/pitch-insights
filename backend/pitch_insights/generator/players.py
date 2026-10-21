"""Clubs, players, lineups and history for the synthetic generator.

Attributes are derived from each player's position, overall quality and traits in
teams.yaml, plus a small per-player offset that is stable across matches.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

TEAMS_FILE = Path(__file__).with_name("teams.yaml")

ATTRS = ("passing", "vision", "dribbling", "shooting", "pace", "defending",
         "pressing", "stamina", "aerial", "goalkeeping")

# Attribute values for a quality-75 player in each position.
POSITION_BASE = {
    "GK": dict(passing=55, vision=50, dribbling=30, shooting=20, pace=45, defending=30, pressing=30, stamina=60, aerial=70, goalkeeping=78),
    "CB": dict(passing=65, vision=55, dribbling=50, shooting=35, pace=62, defending=78, pressing=62, stamina=72, aerial=78, goalkeeping=10),
    "FB": dict(passing=70, vision=62, dribbling=66, shooting=45, pace=78, defending=70, pressing=70, stamina=80, aerial=60, goalkeeping=10),
    "DM": dict(passing=76, vision=70, dribbling=62, shooting=52, pace=62, defending=75, pressing=74, stamina=80, aerial=66, goalkeeping=10),
    "CM": dict(passing=78, vision=75, dribbling=70, shooting=62, pace=66, defending=62, pressing=70, stamina=80, aerial=58, goalkeeping=10),
    "AM": dict(passing=78, vision=80, dribbling=80, shooting=72, pace=72, defending=40, pressing=60, stamina=72, aerial=50, goalkeeping=10),
    "W":  dict(passing=70, vision=70, dribbling=80, shooting=70, pace=84, defending=40, pressing=62, stamina=76, aerial=48, goalkeeping=10),
    "ST": dict(passing=64, vision=64, dribbling=72, shooting=82, pace=76, defending=32, pressing=62, stamina=72, aerial=70, goalkeeping=10),
}

TRAIT_BOOST = {
    "playmaker": {"passing": 7, "vision": 9},
    "speedster": {"pace": 9, "dribbling": 3},
    "finisher": {"shooting": 9},
    "target_man": {"aerial": 10, "shooting": 2},
    "presser": {"pressing": 9, "stamina": 5},
    "ball_winner": {"defending": 7, "pressing": 5},
    "dribbler": {"dribbling": 9},
    "sweeper_keeper": {"passing": 10, "vision": 6},
    "crosser": {"passing": 4, "vision": 4},
}

# Formation slots: (role, accepted positions in order of preference, anchor x, anchor y).
# Anchors are a neutral mid-block shape in the team's own attacking frame.
_BACK4 = [
    ("GK", ("GK",), 5, 34),
    ("LB", ("FB", "CB"), 30, 60),
    ("LCB", ("CB", "DM", "FB"), 22, 45),
    ("RCB", ("CB", "DM", "FB"), 22, 23),
    ("RB", ("FB", "CB"), 30, 8),
]
FORMATIONS = {
    "4-3-3": _BACK4 + [
        ("DM", ("DM", "CM"), 38, 34),
        ("LCM", ("CM", "AM", "DM"), 48, 46),
        ("RCM", ("CM", "AM", "DM"), 48, 22),
        ("LW", ("W", "AM", "ST"), 66, 60),
        ("RW", ("W", "AM", "ST"), 66, 8),
        ("ST", ("ST", "W", "AM"), 74, 34),
    ],
    "4-2-3-1": _BACK4 + [
        ("LDM", ("DM", "CM"), 38, 42),
        ("RDM", ("CM", "DM"), 38, 26),
        ("LW", ("W", "AM", "FB"), 62, 58),
        ("AM", ("AM", "CM", "W"), 58, 34),
        ("RW", ("W", "AM", "FB"), 62, 10),
        ("ST", ("ST", "W", "AM"), 74, 34),
    ],
    "4-4-2": _BACK4 + [
        ("LM", ("W", "AM", "FB"), 52, 60),
        ("LCM", ("CM", "DM", "AM"), 44, 42),
        ("RCM", ("DM", "CM", "AM"), 44, 26),
        ("RM", ("W", "AM", "FB"), 52, 8),
        ("LST", ("ST", "AM", "W"), 70, 40),
        ("RST", ("ST", "AM", "W"), 70, 28),
    ],
    "4-1-4-1": _BACK4 + [
        ("DM", ("DM", "CM"), 34, 34),
        ("LM", ("W", "AM", "FB"), 50, 60),
        ("LCM", ("CM", "AM", "DM"), 46, 44),
        ("RCM", ("AM", "CM", "DM"), 46, 24),
        ("RM", ("W", "AM", "FB"), 50, 8),
        ("ST", ("ST", "W", "AM"), 68, 34),
    ],
}

# Season rates per appearance, by position.
GOAL_RATE = {"ST": 0.45, "W": 0.24, "AM": 0.24, "CM": 0.09, "DM": 0.04, "FB": 0.03, "CB": 0.04, "GK": 0.0}
ASSIST_RATE = {"ST": 0.12, "W": 0.2, "AM": 0.25, "CM": 0.12, "DM": 0.05, "FB": 0.1, "CB": 0.02, "GK": 0.0}


@dataclass(frozen=True)
class PlayerDef:
    id: str
    name: str
    number: int
    position: str
    foot: str
    quality: int
    traits: tuple[str, ...]
    attributes: dict[str, int]


@dataclass(frozen=True)
class ClubDef:
    id: str
    name: str
    short_name: str
    venue: str
    colours: dict[str, str]
    formation: str
    style: str
    players: tuple[PlayerDef, ...]

    def player(self, pid: str) -> PlayerDef:
        return next(p for p in self.players if p.id == pid)


@dataclass
class Lineup:
    starting: list[tuple[str, PlayerDef]]  # (slot role, player)
    bench: list[PlayerDef]
    form: dict[str, int] = field(default_factory=dict)


def _stable_offset(pid: str, attr: str) -> int:
    """A per-player, per-attribute offset in -5..5 that never changes between runs."""
    h = hashlib.sha256(f"{pid}:{attr}".encode()).digest()
    return h[0] % 11 - 5


def _derive_attributes(pid: str, position: str, quality: int, traits: tuple[str, ...]) -> dict[str, int]:
    base = POSITION_BASE[position]
    out = {}
    for a in ATTRS:
        v = base[a] + (quality - 75) * 0.9 + _stable_offset(pid, a)
        for t in traits:
            v += TRAIT_BOOST.get(t, {}).get(a, 0)
        if a == "goalkeeping" and position != "GK":
            v = 8 + _stable_offset(pid, a)
        out[a] = int(max(20 if a != "goalkeeping" else 1, min(99, round(v))))
    return out


def _parse_player(club_id: str, line: str, overrides: dict) -> PlayerDef:
    number, name, position, foot, quality, traits = [s.strip() for s in line.split("|")]
    pid = f"{club_id}-{int(number):02d}"
    trait_list = tuple(t.strip() for t in traits.split(",") if t.strip())
    attrs = _derive_attributes(pid, position, int(quality), trait_list)
    attrs.update(overrides.get(pid, {}))
    return PlayerDef(pid, name, int(number), position, foot, int(quality), trait_list, attrs)


@lru_cache(maxsize=1)
def load_clubs(path: Path = TEAMS_FILE) -> dict[str, ClubDef]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    overrides = data.get("overrides") or {}
    clubs = {}
    for c in data["clubs"]:
        players = tuple(_parse_player(c["id"], line, overrides) for line in c["players"])
        clubs[c["id"]] = ClubDef(
            id=c["id"], name=c["name"], short_name=c["short_name"], venue=c["venue"],
            colours=c["colours"], formation=c["formation"], style=c["style"], players=players,
        )
    return clubs


@lru_cache(maxsize=1)
def league_info(path: Path = TEAMS_FILE) -> tuple[str, int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["league"], int(data["season_matchday"])


def pick_lineup(club: ClubDef, rng: random.Random) -> Lineup:
    """Choose a starting 11 for the club's formation and a 9-man bench, with seeded match form."""
    form = {p.id: rng.randint(-5, 5) for p in club.players}
    available = list(club.players)
    starting: list[tuple[str, PlayerDef]] = []
    for role, accepted, _, _ in FORMATIONS[club.formation]:
        def score(p: PlayerDef) -> float:
            if p.position not in accepted:
                return -1e9
            return p.quality + form[p.id] * 0.4 - accepted.index(p.position) * 6 + rng.uniform(-2, 2)
        best = max(available, key=score)
        starting.append((role, best))
        available.remove(best)
    available.sort(key=lambda p: -(p.quality + form[p.id] * 0.4))
    keepers = [p for p in available if p.position == "GK"]
    bench = (keepers[:1] + [p for p in available if p.position != "GK"])[:9]
    return Lineup(starting=starting, bench=bench, form=form)


def _run_text(last5: list[str]) -> str:
    latest = last5[-1]
    n = 0
    for r in reversed(last5):
        if r == latest:
            n += 1
        else:
            break
    if latest == "W":
        return f"won {n} in a row" if n > 1 else "won last match"
    if latest == "L":
        return f"lost {n} in a row" if n > 1 else "lost last match"
    unbeaten = 0
    for r in reversed(last5):
        if r == "L":
            break
        unbeaten += 1
    return f"unbeaten in {unbeaten}"


def club_strength(club: ClubDef) -> float:
    top = sorted((p.quality for p in club.players), reverse=True)[:11]
    return sum(top) / len(top)


def player_history(p: PlayerDef, matchday: int, squad_rank: int, rng: random.Random) -> dict:
    played_share = 0.88 if squad_rank < 11 else 0.45 if squad_rank < 16 else 0.2
    apps = max(0, min(matchday - 1, round((matchday - 1) * played_share + rng.uniform(-2, 2))))
    skill = (p.attributes["shooting"] / 80) ** 2
    goals = sum(rng.random() < GOAL_RATE[p.position] * skill for _ in range(apps))
    assists = sum(rng.random() < ASSIST_RATE[p.position] * (p.attributes["vision"] / 75) for _ in range(apps))
    clean = sum(rng.random() < 0.32 for _ in range(apps)) if p.position == "GK" else 0
    career = goals + sum(rng.random() < GOAL_RATE[p.position] * skill for _ in range(rng.randint(0, 90)))
    ratings = [round(max(5.0, min(9.5, 6.4 + (p.quality - 75) / 12 + rng.gauss(0, 0.6))), 1) for _ in range(5)]
    return dict(season_apps=apps, season_goals=goals, season_assists=assists,
                season_clean_sheets=clean, club_career_goals=career, last5_ratings=ratings)


def team_history(club: ClubDef, opponent: ClubDef, rng: random.Random) -> dict:
    s, o = club_strength(club), club_strength(opponent)
    position = int(max(1, min(20, round(10 - (s - 76) * 1.6 + rng.gauss(0, 2)))))
    p_win = max(0.15, min(0.7, 0.4 + (s - 76) * 0.05))
    p_draw = 0.26
    last5 = [("W" if (r := rng.random()) < p_win else "D" if r < p_win + p_draw else "L") for _ in range(5)]
    total = rng.randint(6, 14)
    edge = max(0.15, min(0.65, 0.38 + (s - o) * 0.04))
    wins = sum(rng.random() < edge for _ in range(total))
    draws = sum(rng.random() < 0.27 for _ in range(total - wins))
    return dict(league_position=position, last5=last5, current_run=_run_text(last5),
                head_to_head={"wins": wins, "draws": draws, "losses": total - wins - draws})
