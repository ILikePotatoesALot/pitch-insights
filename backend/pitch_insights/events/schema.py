"""Event format v1: the contract shared by every part of Pitch Insights.

See docs/DESIGN.md. Coordinates are metres on a 105 x 68 pitch, always from the
acting team's attacking direction (x = 105 is the goal they attack).
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = "1.0"
PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

X = Annotated[float, Field(ge=0, le=PITCH_LENGTH)]
Y = Annotated[float, Field(ge=0, le=PITCH_WIDTH)]
Prob = Annotated[float, Field(ge=0, le=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- events


class EventBase(_Strict):
    schema_: Literal["1.0"] = Field(SCHEMA_VERSION, alias="schema")
    match_id: str
    seq: int = Field(ge=1)
    source: Literal["synthetic", "video"] = "synthetic"
    t: float = Field(ge=0, description="Seconds since the current period started")
    period: Literal[1, 2]
    clock: str = Field(description="Display clock, e.g. \"45+2'\"")
    minute: int = Field(ge=0, le=130)
    team_id: str | None = None
    player_id: str | None = None
    possession_id: int | None = None
    x: X | None = None
    y: Y | None = None
    under_pressure: bool = False
    confidence: Prob = 1.0

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class MatchState(EventBase):
    type: Literal["match_state"] = "match_state"
    state: Literal["kickoff", "half_time", "full_time"]


class Pass(EventBase):
    type: Literal["pass"] = "pass"
    end_x: X
    end_y: Y
    receiver_id: str | None = None
    outcome: Literal["complete", "incomplete", "out"]
    length: float = Field(ge=0)
    height: Literal["ground", "low", "high"]
    kind: Literal[
        "open_play", "cross", "through_ball", "long_ball", "corner",
        "free_kick", "throw_in", "goal_kick", "kickoff",
    ]
    difficulty: Prob


class Carry(EventBase):
    type: Literal["carry"] = "carry"
    end_x: X
    end_y: Y
    duration: float = Field(ge=0)


class Dribble(EventBase):
    type: Literal["dribble"] = "dribble"
    outcome: Literal["won", "lost"]
    opponent_id: str


class Shot(EventBase):
    type: Literal["shot"] = "shot"
    xg: Prob
    outcome: Literal["goal", "saved", "off_target", "blocked", "woodwork"]
    body_part: Literal["left_foot", "right_foot", "head"]
    kind: Literal["open_play", "penalty", "free_kick", "header", "corner"]
    keeper_id: str | None = None


class Pressure(EventBase):
    type: Literal["pressure"] = "pressure"
    target_player_id: str


class Tackle(EventBase):
    type: Literal["tackle"] = "tackle"
    outcome: Literal["won", "lost"]


class Interception(EventBase):
    type: Literal["interception"] = "interception"
    outcome: Literal["won", "lost"]


class Recovery(EventBase):
    type: Literal["recovery"] = "recovery"
    outcome: Literal["won", "lost"]


class Clearance(EventBase):
    type: Literal["clearance"] = "clearance"
    outcome: Literal["won", "lost"]


class Foul(EventBase):
    type: Literal["foul"] = "foul"
    victim_id: str
    card: Literal["none", "yellow", "red"] = "none"


class Substitution(EventBase):
    type: Literal["substitution"] = "substitution"
    player_off_id: str
    player_on_id: str


Event = Annotated[
    Union[
        MatchState, Pass, Carry, Dribble, Shot, Pressure, Tackle,
        Interception, Recovery, Clearance, Foul, Substitution,
    ],
    Field(discriminator="type"),
]
EVENT_TYPES = (
    "match_state", "pass", "carry", "dribble", "shot", "pressure", "tackle",
    "interception", "recovery", "clearance", "foul", "substitution",
)
event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


# ------------------------------------------------------------ match_meta


class Attributes(_Strict):
    passing: int = Field(ge=0, le=100)
    vision: int = Field(ge=0, le=100)
    dribbling: int = Field(ge=0, le=100)
    shooting: int = Field(ge=0, le=100)
    pace: int = Field(ge=0, le=100)
    defending: int = Field(ge=0, le=100)
    pressing: int = Field(ge=0, le=100)
    stamina: int = Field(ge=0, le=100)
    aerial: int = Field(ge=0, le=100)
    goalkeeping: int = Field(ge=0, le=100)


class PlayerHistory(_Strict):
    season_apps: int
    season_goals: int
    season_assists: int
    season_clean_sheets: int
    club_career_goals: int
    last5_ratings: list[float]


class Player(_Strict):
    id: str
    name: str
    number: int
    position: Literal["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
    foot: Literal["left", "right"]
    attributes: Attributes
    history: PlayerHistory


class TeamHistory(_Strict):
    league_position: int
    last5: list[Literal["W", "D", "L"]]
    current_run: str
    head_to_head: dict[str, int] = Field(description="Keys: wins, draws, losses vs this opponent")


class Team(_Strict):
    id: str
    name: str
    short_name: str
    colours: dict[str, str] = Field(description="Keys: primary, secondary (hex)")
    formation: str
    style: Literal["possession", "high_press", "direct", "counter"]
    starting: list[str] = Field(min_length=11, max_length=11)
    bench: list[str] = Field(max_length=9)
    players: list[Player]
    history: TeamHistory


class MatchInfo(_Strict):
    id: str
    seed: int
    date: str
    competition: str
    matchday: int
    venue: str


class MatchMeta(_Strict):
    type: Literal["match_meta"] = "match_meta"
    schema_: Literal["1.0"] = Field(SCHEMA_VERSION, alias="schema")
    match: MatchInfo
    home: Team
    away: Team
    pitch: dict[str, float] = Field(default_factory=lambda: {"length": PITCH_LENGTH, "width": PITCH_WIDTH})
    attacking_direction: dict[str, dict[str, Literal["left_to_right", "right_to_left"]]] = Field(
        description="Per period ('1', '2'), per team id"
    )

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def dump(model: BaseModel) -> dict:
    """Serialise a model the way it appears on the wire (uses the `schema` alias)."""
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)
