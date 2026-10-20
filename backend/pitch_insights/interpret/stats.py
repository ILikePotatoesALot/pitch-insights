"""Team and player statistics, updated one event at a time."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pitch_insights.interpret import xt

FINAL_THIRD_X = 70.0
HALFWAY_X = 52.5


def in_box(x: float, y: float) -> bool:
    return x > 88.5 and 13.85 < y < 54.15


def is_progressive(e: dict) -> bool:
    """A pass or carry that moves the ball at least 10 m toward goal into the opponent's half, or into the box."""
    return (e["end_x"] - e["x"] >= 10 and e["end_x"] > HALFWAY_X) or (in_box(e["end_x"], e["end_y"]) and not in_box(e["x"], e["y"]))


@dataclass
class TeamStats:
    goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    big_chances: int = 0
    passes: int = 0
    passes_complete: int = 0
    progressive_passes: int = 0
    final_third_entries: int = 0
    crosses: int = 0
    corners: int = 0
    xt_added: float = 0.0
    dribbles_won: int = 0
    pressures: int = 0
    pressures_high: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    recoveries: int = 0
    clearances: int = 0
    defensive_actions_high: int = 0  # tackles, interceptions and fouls in the opponent's 60%
    opp_passes_own_60: int = 0       # opponent passes in their own 60%, for PPDA
    fouls: int = 0
    yellows: int = 0
    reds: int = 0
    subs: int = 0

    def summary(self, opponent: "TeamStats") -> dict:
        d = asdict(self)
        total_passes = self.passes + opponent.passes
        d["possession_pct"] = round(100 * self.passes / total_passes, 1) if total_passes else 50.0
        d["pass_accuracy_pct"] = round(100 * self.passes_complete / self.passes, 1) if self.passes else 0.0
        d["ppda"] = round(self.opp_passes_own_60 / self.defensive_actions_high, 1) if self.defensive_actions_high else None
        d["xg"] = round(self.xg, 2)
        d["xt_added"] = round(self.xt_added, 2)
        return d


@dataclass
class PlayerStats:
    player_id: str
    team_id: str
    name: str
    position: str
    number: int
    on_at: float | None = None   # match seconds when they came on (None = not played yet)
    off_at: float | None = None
    touches: int = 0
    passes: int = 0
    passes_complete: int = 0
    progressive_passes: int = 0
    key_passes: int = 0
    assists: int = 0
    crosses: int = 0
    carries: int = 0
    progressive_carries: int = 0
    xt_added: float = 0.0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    dribbles: int = 0
    dribbles_won: int = 0
    pressures: int = 0
    tackles: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    recoveries: int = 0
    clearances: int = 0
    fouls: int = 0
    fouled: int = 0
    yellow: bool = False
    red: bool = False
    saves: int = 0
    goals_conceded: int = 0
    pass_difficulty_sum: float = 0.0
    pass_lengths: list[float] = field(default_factory=list)

    def minutes(self, now: float) -> float:
        if self.on_at is None:
            return 0.0
        end = self.off_at if self.off_at is not None else now
        return max(0.0, (end - self.on_at) / 60)

    def summary(self, now: float) -> dict:
        d = asdict(self)
        d.pop("pass_lengths")
        d.pop("pass_difficulty_sum")
        d["minutes"] = round(self.minutes(now), 1)
        d["pass_accuracy_pct"] = round(100 * self.passes_complete / self.passes, 1) if self.passes else None
        d["avg_pass_difficulty"] = round(self.pass_difficulty_sum / self.passes, 3) if self.passes else None
        d["avg_pass_length"] = round(sum(self.pass_lengths) / len(self.pass_lengths), 1) if self.pass_lengths else None
        d["xg"] = round(self.xg, 2)
        d["xt_added"] = round(self.xt_added, 3)
        return d


def threat_added(e: dict) -> float:
    """xT gained by a completed pass or a carry (0 for anything else)."""
    if e["type"] == "carry" or (e["type"] == "pass" and e["outcome"] == "complete"):
        return xt.added(e["x"], e["y"], e["end_x"], e["end_y"])
    return 0.0
