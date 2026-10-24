"""The Memory agent: links a moment to similar earlier moments in the same match.

For each headline or notable moment worth remembering (goals, big chances, penalties, red cards
and spells of play), it:

1. describes the moment in one sentence: the team, the player, and how the chance was made
   (cross, through ball, corner, header, which flank, on the break). That sentence is what
   gets embedded;
2. filters earlier moments in code: same family (a goal and a big chance are both chances),
   same team (either team for red cards), and earlier in this match, never later;
3. ranks them by cosine similarity of their embeddings (Foundry text-embedding-3-small,
   256 dimensions) and keeps the best one or two above a threshold;
4. adds `memory` facts to the moment's evidence pack: the similar moments, and a count
   ("That makes 3 Carrot goals or big chances in this match, 2 of them down the left").
   The facts carry their own names and numbers, so the groundedness check accepts them.

Nothing is added when nothing earlier is similar enough, or when a vector is missing.

Vectors for the sample matches are computed ahead of time (scripts/embed_moments.py) and stored
next to each match, so a replay never calls the network:

    samples/comeback-POT-CAR.memory.json

It runs inside MatchBrain, as a deterministic step before the writers, because its facts must
be in the evidence pack that the writers see and the groundedness check reads. See
docs/DESIGN.md, Agents.
"""

from __future__ import annotations

import base64
import functools
import json
import logging
import math
import sys
import time
from array import array
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pitch_insights.agents.store import sibling_path, write_json
from pitch_insights.explain.moments import ordinal

if TYPE_CHECKING:  # imported where it's used (FoundryEmbedder), so the replay server runs without the openai package
    import openai

log = logging.getLogger("pitch_insights.agents")

DIMENSIONS = 256          # text-embedding-3-small shortened from 1,536; plenty for one-sentence moments
THRESHOLD = 0.83          # cosine similarity; calibrated on the three samples (see docs/DESIGN.md)
BATCH = 512               # inputs per embeddings request (the service allows 2,048 and 300,000 tokens)
PROBE_MIN_COSINE = 0.98   # a legacy cache is adopted if one text embeds this close to its stored vector (same model: ~1.0)
COMMENTED_TIERS = {"headline", "notable"}

# Moment type -> family. Only moments of the same family are compared.
FAMILIES = {"goal": "chance", "big_chance_missed": "chance", "penalty_awarded": "penalty", "red_card": "red_card",
            "momentum_swing": "momentum_swing", "dominance": "dominance", "pressing_spell": "pressing_spell"}
EITHER_TEAM = {"red_card"}  # a second red card is worth remembering whoever it went to
TOP_K = {"chance": 2}       # similar moments kept per family; 1 for the rest

ON_BALL = {"pass", "carry", "dribble", "shot"}
SET_PIECES = {"corner", "free_kick", "throw_in", "goal_kick", "kickoff"}
BREAK_S = 15.0            # a chance within this long of winning the ball in your own half is "on the break"
WING = 68 / 3             # each flank is a third of the pitch's width; y = 68 is the attacking team's left
ROUTE = {"left": "down the left", "right": "down the right", "middle": "down the middle",
         "corner": "from a corner", "free_kick": "from a free kick", "penalty": "from the penalty spot"}
ROUTES = ROUTE | {"corner": "from corners", "free_kick": "from free kicks"}  # for counts
BALL_WON = {"interception", "recovery", "tackle"}
MISSED = {"saved": "was saved", "off_target": "went wide", "blocked": "was blocked", "woodwork": "hit the woodwork"}


# ---------------------------------------------------------------- vectors

def normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else []


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two unit vectors."""
    return sum(x * y for x, y in zip(a, b))


def pack(v: list[float]) -> str:
    """A vector as base64 float32, little-endian: a quarter of the size of JSON numbers."""
    arr = array("f", v)
    if sys.byteorder == "big":
        arr.byteswap()
    return base64.b64encode(arr.tobytes()).decode("ascii")


def unpack(s: str) -> list[float]:
    arr = array("f")
    arr.frombytes(base64.b64decode(s))
    if sys.byteorder == "big":
        arr.byteswap()
    return arr.tolist()


class Embedder(Protocol):
    """Anything that gives a moment's description a unit vector, or None if it can't."""

    def vector(self, text: str) -> list[float] | None: ...


class StoredVectors:
    """Vectors computed ahead of time, looked up by the exact text. Remembers every text it was
    asked for, so scripts/embed_moments.py knows what to embed."""

    def __init__(self, vectors: dict[str, list[float]] | None = None, model: str = "", deployment: str = ""):
        self.vectors = vectors or {}
        self.model = model            # what the service reported when it made them
        self.deployment = deployment  # the deployment we asked; "" in files from before it was stored
        self.asked: dict[str, None] = {}  # insertion-ordered set

    def vector(self, text: str) -> list[float] | None:
        self.asked.setdefault(text)
        return self.vectors.get(text)


def memory_path(match_path: Path) -> Path:
    return sibling_path(match_path, ".memory.json")


def load_vectors(match_path: Path) -> StoredVectors:
    """The stored vectors, or none (so no memory facts) if the file is missing, unreadable or
    made with a different number of dimensions."""
    try:
        data = json.loads(memory_path(match_path).read_text(encoding="utf-8"))
        if data["dimensions"] != DIMENSIONS:
            return StoredVectors()
        vectors = {text: normalise(unpack(v)) for text, v in data["vectors"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return StoredVectors()
    if any(len(v) != DIMENSIONS for v in vectors.values()):
        return StoredVectors()
    return StoredVectors(vectors, data.get("model", ""), data.get("deployment", ""))


def write_vectors(match_path: Path, model: str, vectors: dict[str, list[float]], deployment: str = "") -> Path:
    data = {"model": model, "deployment": deployment, "dimensions": DIMENSIONS, "match": match_path.stem,
            "vectors": {text: pack(v) for text, v in vectors.items()}}
    return write_json(memory_path(match_path), data)


def refresh_vectors(stored: StoredVectors, texts: list[str], deployment: str, embed, force: bool = False,
                    ) -> tuple[str, int, bool]:
    """Bring `stored` up to date for `texts` (what scripts/embed_moments.py does for each match).

    `embed(texts)` returns `(model, vectors)`. Vectors from different models can't be compared, so they
    are all made again when `force` is set, when the configured deployment isn't the one the stored
    vectors came from (even if the cache is complete and nothing else needs embedding), or when the
    service reports another model for the new ones. A file from before the deployment was stored can't
    say where its vectors came from, so one of its texts is embedded with the configured deployment and
    compared (same reported model, same vector within rounding) before the file is adopted and stamped.
    Returns the model, how many texts were embedded, and whether stored vectors were thrown away because
    they didn't come from this deployment."""
    changed = bool(stored.deployment) and stored.deployment != deployment
    if force or changed:
        stored.vectors = {}
    elif not stored.deployment:
        probe = next((t for t in texts if t in stored.vectors), None)
        if probe is not None:
            probe_model, (fresh,) = embed([probe])
            if probe_model != stored.model or cosine(fresh, stored.vectors[probe]) < PROBE_MIN_COSINE:
                stored.vectors, changed = {}, True
    todo = [t for t in texts if t not in stored.vectors]
    model = stored.model
    if todo:
        model, vectors = embed(todo)
        if stored.model and model != stored.model and len(todo) < len(texts):
            todo = list(texts)  # the deployment now serves a different model: redo the lot
            model, vectors = embed(todo)
        stored.vectors.update(zip(todo, vectors))
    stored.model, stored.deployment = model, deployment
    return model, len(todo), changed


def embed_batch(client: openai.OpenAI, deployment: str, texts: list[str]) -> tuple[str, list[list[float]]]:
    """Unit vectors for many texts, in as few requests as the service allows. Returns the model
    the service reports and the vectors, in the order of `texts`."""
    model, out = deployment, []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        resp = client.embeddings.create(model=deployment, input=chunk, dimensions=DIMENSIONS)
        data = sorted(resp.data, key=lambda d: d.index)
        if len(data) != len(chunk) or any(len(d.embedding) != DIMENSIONS for d in data):
            raise ValueError("the embeddings response doesn't match the request")
        out += [normalise(d.embedding) for d in data]
        model = resp.model or model
    return model, out


class FoundryEmbedder:
    """Live mode: embeds each new moment as it happens, through the Foundry deployment.

    Any failure (after the SDK's own retries) means no memory facts for that moment, and calls
    pause for a minute so a struggling service doesn't slow the match down. The call blocks, so
    a live server should run MatchBrain off the event loop.
    """

    PAUSE_S = 60.0

    def __init__(self, client: openai.OpenAI, deployment: str):
        self.client, self.deployment = client, deployment
        self.cache: dict[str, list[float]] = {}
        self._paused_until = 0.0

    def vector(self, text: str) -> list[float] | None:
        if text in self.cache:
            return self.cache[text]
        if time.monotonic() < self._paused_until:
            return None
        import openai
        try:
            _, [v] = embed_batch(self.client, self.deployment, [text])
        except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError) as e:
            # Bad key, no access or wrong deployment: no retry can fix it, so stop for the match.
            log.error(json.dumps({"event": "memory_embedding_disabled", "error": type(e).__name__,
                                  "status": e.status_code}))
            self._paused_until = math.inf
            return None
        except openai.BadRequestError as e:
            log.warning(json.dumps({"event": "memory_embedding_refused", "status": e.status_code}))
            return None  # this text only; the next one may be fine
        except (openai.OpenAIError, ValueError) as e:
            log.warning(json.dumps({"event": "memory_embedding_failed", "error": type(e).__name__}))
            self._paused_until = time.monotonic() + self.PAUSE_S
            return None
        self.cache[text] = v
        return v


# ---------------------------------------------------------------- the agent

class MemoryAgent:
    """Feed it every event and the moments MatchBrain makes from it; it adds memory facts to
    headline and notable moments in place."""

    def __init__(self, meta: dict, embedder: Embedder, threshold: float = THRESHOLD):
        self.embedder, self.threshold = embedder, threshold
        self.short = {meta[s]["id"]: meta[s]["short_name"] for s in ("home", "away")}
        self.club = {meta[s]["id"]: meta[s]["name"] for s in ("home", "away")}
        self.surname = {p["id"]: p["name"].split()[-1] for s in ("home", "away") for p in meta[s]["players"]}
        self.records: list[dict] = []  # remembered moments so far, oldest first
        self.links: dict[str, list[tuple[str, float]]] = {}  # moment id -> (earlier moment id, similarity)
        self._phase: list[dict] = []  # the attacking team's on-ball events since the last shot or set piece
        self._possession: tuple | None = None  # ((period, possession id, team), start time, start x)

    def update(self, ev: dict, moments: list[dict]) -> None:
        self._observe(ev)
        for m in moments:
            family = FAMILIES.get(m["type"])
            if family is None:
                continue
            rec = self._describe(m, family)
            rec["vector"] = self.embedder.vector(rec["text"])
            if m["tier"] in COMMENTED_TIERS and rec["vector"] is not None:
                m["facts"] += self._recall(rec)
            self.records.append(rec)

    # ------------------------------------------------------------ build-up

    def _observe(self, ev: dict) -> None:
        if (ev.get("possession_id") is None and ev["type"] in BALL_WON and ev.get("outcome") == "won"
                and self._possession is not None and ev.get("team_id") != self._possession[0][2]):
            self._possession = None  # without possession ids (video), winning the ball ends a possession
        if ev["type"] not in ON_BALL or not ev.get("team_id"):
            return
        key = (ev["period"], ev.get("possession_id"), ev["team_id"])
        if self._possession is None or self._possession[0] != key:
            self._possession = (key, ev["t"], ev["x"])
            self._phase = []
        elif self._phase and (self._phase[-1]["type"] == "shot"
                              or (ev["type"] == "pass" and ev.get("kind") in SET_PIECES)):
            self._phase = []
        self._phase.append(ev)

    def _name(self, pid: str | None) -> str:
        return self.surname.get(pid, "") if pid else ""

    def _chance(self, m: dict) -> tuple[str, str, str]:
        """How a goal or big chance came about: as a phrase for the fact, with every name; as a
        phrase to embed, which names only the scorer, after how the chance was made, so a shared
        build-up counts for more than a shared name; and its route (a key of ROUTE)."""
        shot = self._phase[-1] if self._phase and self._phase[-1]["seq"] == m["seq"] else None
        who = self._name(m["player_id"])
        if shot is None or shot["type"] != "shot":
            fact = f"{who} scored" if m["type"] == "goal" else f"{who} missed a big chance"
            return fact, f"{ROUTE['middle']}: a shot, by {who}", "middle"
        goal = shot["outcome"] == "goal"
        missed = MISSED.get(shot["outcome"], "missed")
        result, that = ("", "") if goal else (" " + missed, " that " + missed)
        if shot["kind"] in ("penalty", "free_kick"):
            route = shot["kind"]
            label = "penalty" if route == "penalty" else "direct free kick"
            fact = (f"{who} scored from the penalty spot" if route == "penalty" else f"{who} scored with a direct free kick") \
                if goal else f"{who}'s {label}{result}"
            return fact, f"{ROUTE[route]}: a {label}{that}, by {who}", route

        before = self._phase[:-1]
        key = next((e for e in reversed(before) if e["type"] == "pass" and e.get("receiver_id") == shot["player_id"]
                    and e.get("outcome") == "complete"), None)
        start = before[0] if before else None
        set_piece = (start is not None and start["type"] == "pass" and start.get("kind") in ("corner", "free_kick")
                     and sum(e["type"] == "pass" for e in before) <= 2)
        if set_piece:
            route = start["kind"]
            label = "corner" if route == "corner" else "free kick"
            named, plain = ((f"from {self._name(start['player_id'])}'s {label}", f"from a {label}") if key is start
                            else (f"after a {label}",) * 2)
        else:
            if key is not None:
                y = key["y"]
                kind = {"cross": "cross", "through_ball": "through ball", "long_ball": "long ball"}.get(key.get("kind"), "pass")
                named, plain = f"from {self._name(key['player_id'])}'s {kind}", f"from a {kind}"
            else:
                run = next((e for e in reversed(before)
                            if e["player_id"] == shot["player_id"] and e["type"] in ("carry", "dribble")), None)
                y = (run or shot)["y"]
                named = plain = "after a run with the ball" if run else ""
            route = "left" if y > 68 - WING else "right" if y < WING else "middle"
        in_box = shot["x"] >= 105 - 16.5 and 34 - 20.16 <= shot["y"] <= 34 + 20.16
        technique = ("a " if in_box else "a long-range ") + ("header" if shot.get("body_part") == "head" else "shot")
        _, poss_t, poss_x = self._possession
        on_break = ", on the break" if poss_x < 52.5 and shot["t"] - poss_t <= BREAK_S else ""
        how = " ".join(p for p in (named, "" if set_piece else ROUTE[route]) if p) + on_break
        embed = f"{ROUTE[route]}{on_break}: " + " ".join(p for p in (technique, plain) if p) + f"{that}, by {who}"
        if goal:
            return f"{who} scored with {technique} {how}".rstrip(), embed, route
        if on_break:
            how += ","
        return f"{who}'s {technique.removeprefix('a ')} {how}{result}", embed, route

    # ------------------------------------------------------------ records and facts

    def _describe(self, m: dict, family: str) -> dict:
        """What to remember about a moment: the text to embed, and the fact to show if a later
        moment finds it similar."""
        team, clock = m["team_id"], m["clock"]
        short, club = self.short.get(team, ""), self.club.get(team, "")
        rec = {"id": m["id"], "seq": m["seq"], "clock": clock, "family": family, "team": team, "route": None}
        if family == "chance":
            phrase, embed, rec["route"] = self._chance(m)
            xg = next((f["value"] for f in m["facts"] if f["kind"] == "chance"), None)
            rec["text"] = f"{club} {'goal' if m['type'] == 'goal' else 'big chance'} {embed}."
            rec["fact"] = f"Earlier in this match, at {clock}: {phrase}" + (f" (xG {xg:.2f})." if xg is not None else ".")
        elif family == "penalty":
            fouler = next((self._name(f["value"]) for f in m["facts"] if f["kind"] == "foul"), "")
            victim = self._name(m["player_id"])
            rec["text"] = f"{club} penalty: {fouler} fouled {victim} in the box."
            rec["fact"] = f"Earlier in this match, at {clock}: another penalty to {short}, when {fouler} fouled {victim}."
        elif family == "red_card":
            card = next((f["value"] for f in m["facts"] if f["kind"] == "card"), "red")
            why = "a second yellow card" if card == "second_yellow" else "a straight red card"
            who = self._name(m["player_id"])
            rec["text"] = f"{club} red card: {who} sent off for {why}."
            rec["fact"] = f"Earlier in this match, at {clock}: {who} of {short} was sent off for {why}."
        elif family == "momentum_swing":
            rec["text"] = f"{club} took control of the game."
            rec["fact"] = f"{short} also took control of the game at {clock}."
        elif family == "dominance":
            rec["text"] = f"{club} were dominating the game."
            rec["fact"] = f"{short} were also dominating at {clock}."
        else:
            rate = next((f["value"]["high_pressures_per_min"] for f in m["facts"] if f["kind"] == "pressing"), None)
            rec["text"] = f"{club} turned up the press."
            rec["fact"] = (f"{short} also turned up the press at {clock}"
                           + (f" ({rate} high pressures a minute)." if rate is not None else "."))
        return rec

    def _peers(self, rec: dict) -> list[dict]:
        """Earlier moments this one may be compared with: the filter before any similarity."""
        return [r for r in self.records if r["family"] == rec["family"]
                and (rec["family"] in EITHER_TEAM or r["team"] == rec["team"])]

    def _recall(self, rec: dict) -> list[dict]:
        peers = self._peers(rec)
        scored = [(cosine(rec["vector"], r["vector"]), i, r) for i, r in enumerate(peers) if r["vector"] is not None]
        scored.sort(key=lambda x: (-x[0], -x[1]))  # most similar first; ties go to the most recent
        hits = [(s, r) for s, _, r in scored if s >= self.threshold][:TOP_K.get(rec["family"], 1)]
        if not hits:
            return []
        self.links[rec["id"]] = [(r["id"], round(s, 3)) for s, r in hits]
        facts = [{"kind": "memory", "value": {"moment_id": r["id"], "clock": r["clock"]},
                  "similarity": round(s, 3), "text": r["fact"]} for s, r in hits]
        return facts + [self._count_fact(rec, peers)]

    def _count_fact(self, rec: dict, peers: list[dict]) -> dict:
        """How many moments like this one the match has had, counted in code (never from similarity)."""
        n, short, family = len(peers) + 1, self.short.get(rec["team"], ""), rec["family"]
        value = {"count": n}
        if family == "chance":
            k = sum(r["route"] == rec["route"] for r in peers) + 1
            value |= {"route": rec["route"], "route_count": k}
            text = f"That makes {n} {short} goals or big chances in this match"
            if k == n:
                text += f", {'both' if n == 2 else 'all'} {ROUTES[rec['route']]}."
            elif k >= 2:
                text += f", {k} of them {ROUTES[rec['route']]}."
            else:
                text += "."
        elif family == "penalty":
            text = f"That's {short}'s {ordinal(n)} penalty of the match."
        elif family == "red_card":
            text = f"That's the {ordinal(n)} red card of the match."
        elif family == "momentum_swing":
            text = f"That's the {ordinal(n)} time {short} have taken control in this match."
        elif family == "dominance":
            text = f"That's {short}'s {ordinal(n)} spell of dominance in this match."
        else:
            text = f"That's {short}'s {ordinal(n)} pressing spell of the match."
        return {"kind": "memory", "value": value, "text": text}


@functools.lru_cache(maxsize=16)
def _cached_vectors(match_path: Path, mtime_ns: int | None) -> StoredVectors:
    """Loaded once per file version, not on every replay connection or seek."""
    return load_vectors(match_path)


def memory_for(match_path: Path, meta: dict) -> MemoryAgent:
    """The Memory agent for a stored match, using its precomputed vectors (no network).

    Without them, moments get no memory facts, so stored commentary written with those facts
    no longer matches its moment and isn't shown: the .memory.json files ship with the samples.
    """
    try:
        mtime = memory_path(match_path).stat().st_mtime_ns
    except OSError:
        mtime = None
    vectors = _cached_vectors(match_path, mtime)
    if not vectors.vectors:
        log.warning(json.dumps({"event": "memory_vectors_missing", "match": match_path.stem,
                                "file": memory_path(match_path).name}))
    return MemoryAgent(meta, vectors)
