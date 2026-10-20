"""Match scripts: optional storylines that nudge probabilities.

Example (YAML):

    seed: 42
    home: POT
    away: CAR
    phases:
      - {from: 60, to: 72, team: POT, press: 0.4, directness: 0.2, attack: 0.3}
    forced:
      - {minute: 58, type: red_card, team: CAR}
      - {minute: 65, type: substitution, team: POT}

Phases only change probabilities, so the score is never forced. Red cards and
substitutions can be forced because they are decisions, not luck.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


@dataclass(frozen=True)
class Phase:
    start: int
    end: int
    team: str
    press: float = 0.0       # added to pressing probability
    directness: float = 0.0  # longer, more forward passing
    attack: float = 0.0      # more shots and forward play


@dataclass(frozen=True)
class Forced:
    minute: int
    type: Literal["red_card", "substitution"]
    team: str


@dataclass(frozen=True)
class Script:
    seed: int | None = None
    home: str | None = None
    away: str | None = None
    phases: tuple[Phase, ...] = ()
    forced: tuple[Forced, ...] = field(default_factory=tuple)

    def modifiers(self, team: str, minute: int) -> Phase:
        """Sum of all phase effects active for this team at this minute."""
        press = directness = attack = 0.0
        for p in self.phases:
            if p.team == team and p.start <= minute < p.end:
                press += p.press
                directness += p.directness
                attack += p.attack
        return Phase(minute, minute, team, press, directness, attack)


def load_script(path: str | Path) -> Script:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return script_from_dict(data)


def script_from_dict(data: dict) -> Script:
    phases = tuple(
        Phase(start=p["from"], end=p["to"], team=p["team"], press=p.get("press", 0.0),
              directness=p.get("directness", 0.0), attack=p.get("attack", 0.0))
        for p in data.get("phases", [])
    )
    forced = tuple(Forced(minute=f["minute"], type=f["type"], team=f["team"]) for f in data.get("forced", []))
    return Script(seed=data.get("seed"), home=data.get("home"), away=data.get("away"), phases=phases, forced=forced)
