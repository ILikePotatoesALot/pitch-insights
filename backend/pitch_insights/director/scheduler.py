"""The Director's scheduler: which cues are on screen right now.

Cues come in (`offer`), time passes (`advance`), and the scheduler answers with messages for
the browser: `{"type": "cue", "cue": ...}` when a cue starts and
`{"type": "cue_end", "id": ..., "reason": "expired" | "preempted"}` when one goes. It is plain
code with no clock of its own: every call says what time it is, in seconds on the viewer's
screen (see `ShowClock`), so the same cues at the same times always give the same messages.

The clutter rules (all in `Rules`, so they're config, not code):

- at most one cue of each template at a time, so at most one lower-third;
- at most `max_cards` cards (everything but the lower-third) and `max_total` cues on screen;
- a cooldown after a card of a template ends before the next one of that template, and a
  longer one for the same player's card of that template (his rating alert twice in a minute);
- a cue whose priority beats an occupant's by `preempt_margin` takes its place, once the
  occupant has been up for its template's `min_hold` seconds (so nothing flashes). Urgent cues
  (goals, red cards, the final whistle) don't queue behind each other: the newest replaces an
  older one on screen after its `min_hold`, never the other way round, and when one starts it
  drops the older urgent cues of its template still waiting ("superseded");
- a cue that can't start waits in a short queue, highest priority first, and is dropped when
  it has waited longer than its template's `max_delay` (it would be stale), or when the queue
  is full. Urgent cues (`urgent` and above) skip cooldowns, never the limits.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from pitch_insights.director.cues import CARD_TEMPLATES, TEMPLATES

EPS = 1e-9
DEFAULT_MAX_DELAY = 8.0  # for a template a custom `Rules.max_delay` leaves out


@dataclass(frozen=True)
class Rules:
    max_per_template: dict[str, int] = field(default_factory=lambda: {t: 1 for t in TEMPLATES})
    max_cards: int = 2
    max_total: int = 3
    cooldown: dict[str, float] = field(default_factory=lambda: {
        "stat_card": 20.0, "player_tag": 8.0, "rating_alert": 15.0, "speed_popup": 12.0, "fan_alert": 4.0})
    topic_cooldown: float = 45.0
    preempt_margin: int = 10
    min_hold: dict[str, float] = field(default_factory=lambda: {"lower_third": 4.0, "stat_card": 2.0, "player_tag": 2.0,
                                                                 "rating_alert": 2.0, "speed_popup": 2.0, "fan_alert": 2.0})
    urgent: int = 90
    max_delay: dict[str, float] = field(default_factory=lambda: {
        "lower_third": 8.0, "stat_card": 12.0, "player_tag": 3.0, "rating_alert": 10.0, "speed_popup": 2.0, "fan_alert": 10.0})
    max_pending: int = 4


DEFAULT_RULES = Rules()


class ShowClock:
    """Maps the match clock to seconds on the viewer's screen.

    A cue lasts a number of seconds on the screen, whatever the replay speed, so the scheduler
    works in screen seconds: match time divided by the speed in force when it passed. Pausing
    stops the match clock, so it stops this one too, and a speed change only affects time that
    hasn't passed yet. Never goes backwards."""

    def __init__(self):
        self.show = 0.0
        self._match: float | None = None

    def at(self, match_time: float, speed: float) -> float:
        if self._match is None:
            self._match = match_time
        elif match_time > self._match:
            self.show += (match_time - self._match) / speed
            self._match = match_time
        return self.show


@dataclass
class _Live:
    cue: dict
    start: float
    seq: int  # the order cues were offered in, for tie-breaks (ids are strings: "C-10" sorts before "C-9")

    @property
    def end(self) -> float:
        return self.start + self.cue["duration"]


@dataclass
class _Pending:
    cue: dict
    seq: int
    arrived: float


class Director:
    def __init__(self, rules: Rules = DEFAULT_RULES):
        self.rules = rules
        self._live: list[_Live] = []
        self._pending: list[_Pending] = []
        self._now = 0.0
        self._seq = 0
        self._last_end: dict[str, float] = {}   # template -> when its last cue ended
        self._topic_end: dict[str, float] = {}  # topic -> when its last cue ended
        self.dropped: deque[dict] = deque(maxlen=500)  # what never reached the screen, and why

    # ------------------------------------------------------------ public

    @property
    def on_screen(self) -> list[dict]:
        return [s.cue for s in self._live]

    @property
    def waiting(self) -> int:
        """How many cues are queued. Each starts or is dropped within its template's `max_delay`."""
        return len(self._pending)

    def offer(self, cues: list[dict], now: float) -> list[dict]:
        """New cues arrive. Returns the messages for what changed on screen."""
        now = self._tick(now)
        for cue in cues:
            if cue.get("template") not in TEMPLATES:
                raise ValueError(f"unknown template {cue.get('template')!r}")
            self._seq += 1
            self._pending.append(_Pending(cue | {"id": f"C-{self._seq}"}, self._seq, now))
        out = self._settle(now)
        while len(self._pending) > self.rules.max_pending:
            worst = min(self._pending, key=lambda p: (p.cue["priority"], p.seq))
            self._pending.remove(worst)
            self._drop(worst.cue, "queue_full", now)
        return out

    def advance(self, now: float) -> list[dict]:
        """Time passes. Returns the messages for what changed on screen."""
        return self._settle(self._tick(now))

    def withdraw(self, unwanted, now: float) -> list[dict]:
        """Take away every cue, on screen or waiting, for which `unwanted(cue)` is true (the viewer changed
        mode and will never see them), then let what is waiting have the slots. Withdrawn cues leave no
        cooldown behind: the viewer never saw them."""
        now = self._tick(now)
        out: list[dict] = []
        for s in [s for s in self._live if unwanted(s.cue)]:
            self._live.remove(s)
            out.append({"type": "cue_end", "id": s.cue["id"], "reason": "withdrawn"})
        for p in [p for p in self._pending if unwanted(p.cue)]:
            self._pending.remove(p)
            self._drop(p.cue, "withdrawn", now)
        return out + self._settle(now)

    # ------------------------------------------------------------ rules

    def _tick(self, now: float) -> float:
        self._now = max(self._now, now)
        return self._now

    def _settle(self, now: float) -> list[dict]:
        out: list[dict] = []
        for s in sorted(self._live, key=lambda s: (s.end, s.seq)):
            if now >= s.end - EPS:
                self._end(s, s.end, "expired", out)
        for p in [p for p in self._pending if now - p.arrived > self.rules.max_delay.get(p.cue["template"], DEFAULT_MAX_DELAY) + EPS]:
            self._pending.remove(p)
            self._drop(p.cue, "stale", now)
        # Highest priority first; after each cue starts, look again from the top, because
        # what it took (or pushed off) changes what the others can do.
        while True:
            for p in sorted(self._pending, key=lambda p: (-p.cue["priority"], p.seq)):
                victims = self._admission(p, now)
                if victims is None:
                    continue
                for v in victims:
                    self._end(v, now, "preempted", out)
                self._pending.remove(p)
                cue = p.cue | {"delay": round(now - p.arrived, 2)}
                self._live.append(_Live(cue, now, p.seq))
                out.append({"type": "cue", "cue": cue})
                if cue["priority"] >= self.rules.urgent:  # an older goal banner must not show after a newer one
                    for q in [q for q in self._pending if q.seq < p.seq and q.cue["template"] == cue["template"]
                              and q.cue["priority"] >= self.rules.urgent]:
                        self._pending.remove(q)
                        self._drop(q.cue, "superseded", now)
                break
            else:
                return out

    def _admission(self, p: _Pending, now: float) -> list[_Live] | None:
        """The cues on screen that must make way for this one, or None if it has to wait."""
        r, cue = self.rules, p.cue
        t = cue["template"]
        victims: list[_Live] = []
        while True:
            live = [s for s in self._live if s not in victims]
            cards = [s for s in live if s.cue["template"] in CARD_TEMPLATES]
            same = [s for s in live if s.cue["template"] == t]
            if len(same) >= r.max_per_template.get(t, 1):
                contested = same
            elif t in CARD_TEMPLATES and len(cards) >= r.max_cards:
                contested = cards
            elif len(live) >= r.max_total:
                contested = live
            else:
                break
            v = min(contested, key=lambda s: (s.cue["priority"], s.start, s.seq))
            outranks = cue["priority"] >= v.cue["priority"] + r.preempt_margin
            newest_urgent = cue["priority"] >= r.urgent and v.cue["priority"] >= r.urgent and p.seq > v.seq
            if not (outranks or newest_urgent) or now - v.start < r.min_hold.get(v.cue["template"], 2.0) - EPS:
                return None
            victims.append(v)
        replaces_same = any(v.cue["template"] == t for v in victims)
        if cue["priority"] < r.urgent and not replaces_same:
            if now < self._last_end.get(t, float("-inf")) + r.cooldown.get(t, 0.0) - EPS:
                return None
            if t in CARD_TEMPLATES and cue.get("topic") and now < self._topic_end.get(cue["topic"], float("-inf")) + r.topic_cooldown - EPS:
                return None
        return victims

    def _end(self, s: _Live, at: float, reason: str, out: list[dict]):
        self._live.remove(s)
        self._last_end[s.cue["template"]] = at
        if s.cue.get("topic"):
            self._topic_end[s.cue["topic"]] = at
        out.append({"type": "cue_end", "id": s.cue["id"], "reason": reason})

    def _drop(self, cue: dict, reason: str, now: float):
        self.dropped.append({"id": cue["id"], "template": cue["template"], "priority": cue["priority"],
                             "reason": reason, "at": round(now, 2)})
