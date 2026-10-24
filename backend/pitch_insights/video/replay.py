"""The tracked video clip as something the replay server can stream.

Reads the stored outputs of the video path from `samples/video/` (frames, events, benchmark: plain JSON Lines and
JSON, so the backend needs no torch, opencv or rfdetr) and prepares what the app needs besides the frames:

- `clip_meta`: a `match_meta`-shaped description (two teams, Left and Right, and their attacking directions), so
  the app's colours, overlays and event drawing work as for a synthetic match. It has no squads: the video can't
  read shirt numbers, so there are no names to show.
- `credibility`: the benchmark figures, the model and the credit the app shows next to the positions.
- `describe`: the words for a detected event (a headline and a detail line) in the viewer's language.
- `cue_for_event`: the Overlay Director's cue for a detected event.

Players are only ever labelled by side and tracker number ("Left #12"), never with names (DESIGN.md, Video path).
"""

from __future__ import annotations

import functools
import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path

from pitch_insights.director.cues import cue, lower_third_seconds
from pitch_insights.events.schema import Frame

CLIP_DIR = "video"  # inside the samples folder
# The clips the app lists. The pre-trained run of the same clip sits beside it and can still be opened by name;
# Austin chose the fine-tuned run for the app on 23 Oct (see DESIGN.md, Video path).
APP_CLIPS = ("117093-38min_ft",)
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

SIDES = {"L": ("Left", "#3b82f6", "#1e3a8a"), "R": ("Right", "#f1f5f9", "#475569")}
CREDIT = "SoccerTrack v2 (CC BY 4.0)"
CREDIT_URL = "https://atomscott.github.io/SoccerTrack-v2/"

LONG_PASS_M = 20.0  # a completed pass at least this long is worth a casual fan's attention


class ClipError(ValueError):
    """A clip file that is missing something or doesn't match the frame format."""


@dataclass(frozen=True)
class Clip:
    name: str
    match_id: str
    frames: list[dict]
    events: list[dict]
    benchmark: dict

    @property
    def start(self) -> float:
        """`t` of the first frame: seconds since the period started (38:00 for this clip)."""
        return self.frames[0]["t"]

    @property
    def duration(self) -> float:
        return round(self.frames[-1]["t"] - self.start, 3)

    @property
    def frame_dt(self) -> float:
        return round((self.frames[-1]["t"] - self.start) / (len(self.frames) - 1), 3) if len(self.frames) > 1 else 0.2


def _files(samples: Path, name: str) -> tuple[Path, Path, Path] | None:
    if not NAME.fullmatch(name):
        return None
    base = samples / CLIP_DIR
    paths = (base / f"{name}.frames.jsonl", base / f"{name}.events.jsonl", base / f"{name}.benchmark.json")
    return paths if all(p.is_file() and p.resolve().parent == base.resolve() for p in paths) else None


def _read_lines(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=4)
def _load(name: str, stamps: tuple[tuple[str, int], ...]) -> Clip:
    """Parse a clip once; `stamps` (path and modification time) make a changed file be read again. Whatever is
    wrong with the files (unreadable, truncated, a figure missing from the benchmark) comes out as a ClipError."""
    try:
        clip = _parse(name, [Path(p) for p, _ in stamps])
        credibility(clip)  # every figure the app will ask for is there
        return clip
    except ClipError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ClipError(f"clip {name!r} can't be read: {type(e).__name__}: {e}") from None


EVENT_TYPES = ("pass", "carry", "interception")


def _check_event(file: str, e: dict) -> None:
    """The fields the event words, cues and pitch drawing read must be there and sensible."""
    def bad(why: str):
        raise ClipError(f"{file}: event {e.get('seq')!r} {why}")

    if e.get("type") not in EVENT_TYPES:
        bad(f"has type {e.get('type')!r}, expected one of {EVENT_TYPES}")
    for key, lo, hi in (("seq", 1, 10**9), ("t", 0, 10**6), ("confidence", 0, 1), ("x", 0, 105), ("y", 0, 68)):
        v = e.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            bad(f"needs {key} as a number from {lo:g} to {hi:g}, got {v!r}")
    if e.get("team_id") not in SIDES or not isinstance(e.get("player_id"), str):
        bad("needs a team_id of L or R and a player_id")
    for key, hi in (("end_x", 105), ("end_y", 68)):  # a pass or carry's end point, when it has one
        if key in e and (isinstance(e[key], bool) or not isinstance(e[key], (int, float)) or not 0 <= e[key] <= hi):
            bad(f"has {key} {e[key]!r}, expected a number from 0 to {hi}")


def _parse(name: str, paths: list[Path]) -> Clip:
    frames_path, events_path, bench_path = paths
    frames, events = _read_lines(frames_path), _read_lines(events_path)
    if not frames:
        raise ClipError(f"{frames_path.name} has no frames")
    for f in frames:
        try:
            Frame.model_validate(f)
        except ValueError as e:
            raise ClipError(f"{frames_path.name}: not a valid frame message: {e}") from None
    if any(b["t"] <= a["t"] for a, b in zip(frames, frames[1:])):
        raise ClipError(f"{frames_path.name}: frame times must increase")
    if len({f["match_id"] for f in frames}) != 1 or {f["period"] for f in frames} != {1}:
        raise ClipError(f"{frames_path.name}: expected one match and one period")
    for e in events:
        _check_event(events_path.name, e)
    events.sort(key=lambda e: (e["t"], e["seq"]))
    benchmark = json.loads(bench_path.read_text(encoding="utf-8"))
    return Clip(name, frames[0]["match_id"], frames, events, benchmark)


def find_clip(samples: Path, name: str) -> Clip | None:
    """The clip called `name` in `samples/video/`, or None when there isn't one (or the name isn't a plain file name)."""
    paths = _files(samples, name)
    if paths is None:
        return None
    return _load(name, tuple((str(p), p.stat().st_mtime_ns) for p in paths))


def list_clips(samples: Path) -> list[dict]:
    """What `GET /api/matches` lists for the clips: the same shape as a match, with `kind: "video"`."""
    out = []
    for name in APP_CLIPS:
        try:
            clip = find_clip(samples, name)
        except ClipError as e:  # a damaged clip must not take the synthetic matches down with it
            log.warning("clip not listed: %s", e)
            continue
        if clip:
            meta = clip_meta(clip)
            out.append({"name": name, "kind": "video", "match_id": clip.match_id,
                        "home": {k: meta["home"][k] for k in ("id", "name", "short_name", "colours")},
                        "away": {k: meta["away"][k] for k in ("id", "name", "short_name", "colours")}})
    return out


# ------------------------------------------------------------------ what the app is told about the clip

def mmss(t: float) -> str:
    """Time into the half as the match clock shows it: 2280 s is 38:00."""
    s = int(t)
    return f"{s // 60}:{s % 60:02d}"


def clip_meta(clip: Clip) -> dict:
    """A `match_meta`-shaped description of the clip, so the app treats it like a match (Left is "home")."""
    def team(side: str) -> dict:
        name, primary, secondary = SIDES[side]
        return {"id": side, "name": name, "short_name": name, "colours": {"primary": primary, "secondary": secondary},
                "formation": "", "style": "", "starting": [], "bench": [], "players": []}

    clock = f"{mmss(clip.start)}–{mmss(round(clip.start + clip.duration))}"  # (99.8 s of frames is the 100 s clip)
    return {"type": "match_meta", "source": "video",
            "match": {"id": clip.match_id, "seed": 0, "competition": "SoccerTrack v2, real footage", "matchday": 0,
                      "venue": "University pitch, fixed 4K camera", "title": f"Real footage: first half, {clock}"},
            "home": team("L"), "away": team("R"),
            # SoccerTrack: the left team attacks towards +x in this half, as our home team does.
            "attacking_direction": {"1": {"L": "left_to_right", "R": "right_to_left"}}}


def _number(source: dict, key: str, lo: float, hi: float, whole: bool = False) -> float:
    """A figure from a stored file that must be a real number in [lo, hi] (a null, a string, a bool, NaN or a
    percentage typed as 97 for 0.97 would otherwise reach the app and break it)."""
    v = source[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi or (whole and v != int(v)):
        raise ClipError(f"benchmark: {key!r} must be {'a whole number' if whole else 'a number'} from {lo:g} to {hi:g}, got {v!r}")
    return int(v) if whole else v


def _text(source: dict, key: str) -> str:
    v = source[key]
    if not isinstance(v, str) or not v.strip():
        raise ClipError(f"benchmark: {key!r} must be text, got {v!r}")
    return v


def credibility(clip: Clip) -> dict:
    """The figures behind the positions, straight from the benchmark file, and what they do and don't cover.
    Every value is checked (type and range), so a damaged benchmark is a ClipError at load, never a crash in the app."""
    b = clip.benchmark
    tp, ball, ev, detector, span = b["tracked_players"], b["ball"], b["events"]["within_5s"]["all"], b["detector"], b["clip"]
    frames = _number(ball, "frames", 1, 10**7, whole=True)
    ball_frames = _number(ball, "frames_with_ball", 0, frames, whole=True)
    figures = {"precision": _number(tp, "precision", 0, 1), "recall": _number(tp, "recall", 0, 1),
               "position_error_mean_m": _number(tp, "position_error_mean_m", 0, 100),
               "position_error_median_m": _number(tp, "position_error_median_m", 0, 100),
               "position_error_p90_m": _number(tp, "position_error_p90_m", 0, 100),
               "team_accuracy": _number(tp, "team_accuracy", 0, 1), "id_consistency": _number(tp, "id_consistency", 0, 1),
               "tracks": _number(tp, "tracks", 0, 10**6, whole=True),
               "players_on_pitch": _number(tp, "ground_truth_players", 0, 100, whole=True),
               "match_radius_m": _number(tp, "match_radius_m", 0, 100),
               "ball_frames": ball_frames, "frames": frames,
               "event_precision": _number(ev, "precision", 0, 1), "event_recall": _number(ev, "recall", 0, 1)}
    model, fine_tuned = _text(detector, "model"), detector.get("fine_tuned") is True
    from_, to = _text(span, "from"), _text(span, "to")
    pitch = f"{from_} to {to} of the first half"
    return {
        "clip": {"match": _text(span, "match"), "from": from_, "to": to, "frames": len(clip.frames),
                 "fps": _number(span, "fps_processed", 0.1, 1000), "start": clip.start, "duration": clip.duration},
        "model": model, "fine_tuned": fine_tuned, "tiles": detector["tiles"] if isinstance(detector.get("tiles"), str) else None,
        "credit": CREDIT, "credit_url": CREDIT_URL, "figures": figures,
        "limits": [
            f"Positions come from a computer-vision model reading the video, not from tags or a data feed, so some "
            f"are off or missing. Scored on one {round(clip.duration)}-second clip ({pitch}) against SoccerTrack's "
            f"own tracking labels, which have no referees and no ball.",
            "The model was fine-tuned on the first four minutes of this same half (never on this clip), so the "
            "figures may not carry over to another pitch or match." if fine_tuned else
            "The model is used as released, with no fine-tuning.",
            "Numbers after # are tracker IDs, not shirt numbers, and a player can get a new ID after being hidden. "
            "Grey markers are people the model could not give a team (keepers, officials).",
            f"The ball is followed in {ball_frames} of {frames} frames and is not scored. "
            "Passes, carries and interceptions are inferred from it; shots are not detected.",
        ],
    }


# ------------------------------------------------------------------ labels and words

def player_label(player_id: str | None) -> str:
    """"L-t12" is "Left #12"; a track with no team ("X-t5") is "Track #5". Never a name."""
    m = re.fullmatch(r"([A-Z])-t(\d+)", player_id or "")
    if not m:
        return "Unknown"
    side, n = m.groups()
    return f"{SIDES[side][0]} #{n}" if side in SIDES else f"Track #{n}"


# The wording of the detected events. Written by us, not machine-translated by a service; the labels ("Left #11")
# and the numbers are the same in every language. {who} is the actor ("Left #11"), {to} the receiver ("#6").
PHRASES: dict[str, dict[str, str]] = {
    "en": {"pass": "{who} passes to {to}", "pass_incomplete": "{who}'s pass goes astray", "interception": "{who} wins the ball",
           "carry": "{who} runs with the ball", "detail": "Detected from the video · {m} m · confidence {c}%",
           "detail_short": "Detected from the video · confidence {c}%"},
    "es": {"pass": "{who} pasa a {to}", "pass_incomplete": "El pase de {who} no llega", "interception": "{who} recupera el balón",
           "carry": "{who} avanza con el balón", "detail": "Detectado en el vídeo · {m} m · confianza {c} %",
           "detail_short": "Detectado en el vídeo · confianza {c} %"},
    "fr": {"pass": "{who} passe à {to}", "pass_incomplete": "La passe de {who} n'arrive pas", "interception": "{who} récupère le ballon",
           "carry": "{who} progresse avec le ballon", "detail": "Détecté sur la vidéo · {m} m · confiance {c} %",
           "detail_short": "Détecté sur la vidéo · confiance {c} %"},
    "de": {"pass": "{who} passt zu {to}", "pass_incomplete": "Pass von {who} kommt nicht an", "interception": "{who} erobert den Ball",
           "carry": "{who} treibt den Ball nach vorn", "detail": "Im Video erkannt · {m} m · Sicherheit {c} %",
           "detail_short": "Im Video erkannt · Sicherheit {c} %"},
    "nl": {"pass": "{who} speelt naar {to}", "pass_incomplete": "De pass van {who} komt niet aan", "interception": "{who} pakt de bal af",
           "carry": "{who} dribbelt met de bal", "detail": "In de video herkend · {m} m · zekerheid {c}%",
           "detail_short": "In de video herkend · zekerheid {c}%"},
    "zh-Hans": {"pass": "{who}传球给{to}", "pass_incomplete": "{who}的传球未到位", "interception": "{who}抢到球",
                "carry": "{who}带球推进", "detail": "视频识别 · {m} 米 · 置信度 {c}%",
                "detail_short": "视频识别 · 置信度 {c}%"},
}


def _key(ev: dict) -> str:
    if ev["type"] == "pass":
        return "pass" if ev.get("outcome") == "complete" else "pass_incomplete"
    return ev["type"]


def event_length(ev: dict) -> float | None:
    """Metres a pass or carry covered, or None for an event with no end point."""
    if ev.get("length") is not None:
        return float(ev["length"])
    if ev.get("end_x") is not None and ev.get("end_y") is not None:
        return round(((ev["end_x"] - ev["x"]) ** 2 + (ev["end_y"] - ev["y"]) ** 2) ** 0.5, 1)
    return None


def describe(ev: dict, lang: str = "en") -> tuple[str, str]:
    """A detected event in words: (headline, detail line). An unknown language falls back to English."""
    p = PHRASES.get(lang, PHRASES["en"])
    metres = event_length(ev) if ev["type"] in ("pass", "carry") else None
    to = "#" + ev["receiver_id"].rsplit("t", 1)[-1] if ev.get("receiver_id") else "?"
    headline = p.get(_key(ev), PHRASES["en"].get(_key(ev), ev["type"])).format(who=player_label(ev.get("player_id")), to=to)
    c = round(100 * ev["confidence"])
    detail = (p["detail"].format(m=round(metres), c=c) if metres is not None else p["detail_short"].format(c=c))
    return headline, detail


def cue_for_event(ev: dict, lang: str = "en") -> dict:
    """The lower-third for a detected event. Interceptions, passes that fail and long passes are for every viewer
    (they are what a fan would have noticed); short passes and carries are for analysts."""
    headline, detail = describe(ev, lang)
    metres = event_length(ev) or 0.0
    notable = (ev["type"] == "interception" or (ev["type"] == "pass" and (ev.get("outcome") != "complete" or metres >= LONG_PASS_M)))
    priority = (62 if notable else 38) + 20 * ev["confidence"]
    return cue("lower_third", ev["t"], lower_third_seconds(None, detail, None), priority,
               tier="notable" if notable else "minor", detail="casual" if notable else "analyst", moment_id=None,
               team_id=ev.get("team_id"), player_id=ev.get("player_id"),
               data={"kind": ev["type"], "clock": mmss(ev["t"]), "headline": headline, "casual": None,
                     "analyst": detail, "fact": detail, "confidence": ev["confidence"]})
