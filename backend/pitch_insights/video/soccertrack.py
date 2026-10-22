"""SoccerTrack v2 loader: GSR tracking ground truth and BAS events.

The GSR file for one half is about 2.7 GB of pretty-printed JSON, so it is read
as a stream: one array item at a time, never the whole file. The shipped files
differ from SoccerTrack's written spec (see docs/DESIGN.md, "Their annotations"):

- COCO-style: `info`, `images`, `annotations`, `categories`. `images` comes
  before `annotations` and maps each `image_id` to a 1-based frame number
  (`file_name` "000123.jpg").
- Fields sit under `attributes`; shirt numbers are strings.
- The pitch position is `bbox_pitch.x_bottom_middle` / `y_bottom_middle`, in
  metres from the centre spot, x towards the right goal, y towards the camera.
  Positions are on a grid of 1% of the pitch (1.05 m by 0.68 m).
- `bbox_image` boxes are approximate (every box is 43 px tall) and the ball is
  not annotated. There is no camera calibration in the file.
- `team` is the side ("left"/"right") in that half; the left team attacks +x.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, TextIO

from ..events.schema import PITCH_LENGTH, PITCH_WIDTH

HALF_LENGTH = PITCH_LENGTH / 2
HALF_WIDTH = PITCH_WIDTH / 2


# ------------------------------------------------------------ coordinates


def to_our_frame(x_st: float, y_st: float, attacks_plus_x: bool) -> tuple[float, float]:
    """SoccerTrack metres (origin at the centre spot) to our 105 x 68 frame.

    Ours is always from the acting team's attacking direction, so the team
    attacking towards -x gets the same 180-degree flip the generator uses.
    """
    if attacks_plus_x:
        return x_st + HALF_LENGTH, y_st + HALF_WIDTH
    return HALF_LENGTH - x_st, HALF_WIDTH - y_st


def from_our_frame(x: float, y: float, attacks_plus_x: bool) -> tuple[float, float]:
    """The inverse of `to_our_frame`."""
    if attacks_plus_x:
        return x - HALF_LENGTH, y - HALF_WIDTH
    return HALF_LENGTH - x, HALF_WIDTH - y


def attacks_plus_x(side: str) -> bool:
    """Within one half's files, the left team attacks towards +x."""
    if side not in ("left", "right"):
        raise ValueError(f"unknown side {side!r}")
    return side == "left"


# --------------------------------------------------------- JSON streaming


class _Stream:
    """A growing text buffer over a file, for `json.JSONDecoder.raw_decode`."""

    def __init__(self, f: TextIO, chunk_size: int, max_value_chars: int) -> None:
        self.f = f
        self.chunk_size = chunk_size
        self.max_value_chars = max_value_chars
        self.buf = ""
        self.pos = 0
        self.eof = False

    def _fill(self) -> bool:
        if self.eof:
            return False
        chunk = self.f.read(self.chunk_size)
        if not chunk:
            self.eof = True
            return False
        if self.pos > len(self.buf) // 2:
            self.buf = self.buf[self.pos:]
            self.pos = 0
        self.buf += chunk
        return True

    def peek(self) -> str:
        """The next character that isn't whitespace ("" at the end)."""
        while True:
            while self.pos < len(self.buf) and self.buf[self.pos] in " \t\r\n":
                self.pos += 1
            if self.pos < len(self.buf):
                return self.buf[self.pos]
            if not self._fill():
                return ""

    def expect(self, ch: str) -> None:
        got = self.peek()
        if got != ch:
            raise ValueError(f"expected {ch!r}, found {got!r}")
        self.pos += 1

    def value(self, decoder: json.JSONDecoder) -> Any:
        self.peek()
        while True:
            try:
                obj, end = decoder.raw_decode(self.buf, self.pos)
            except json.JSONDecodeError:
                # Incomplete (read more) or malformed: a value can't be bigger
                # than the limit, so a bad byte fails here, not after reading
                # the rest of a multi-gigabyte file into memory.
                if len(self.buf) - self.pos <= self.max_value_chars and self._fill():
                    continue
                raise
            # A number can end exactly at the buffer's end and still go on.
            if end == len(self.buf) and self._fill():
                continue
            self.pos = end
            return obj


def iter_top_level(
    path: str | Path, chunk_size: int = 1 << 20, max_value_chars: int = 64 << 20,
) -> Iterator[tuple[str, Any]]:
    """Stream a JSON object's top-level members.

    Yields `(key, item)` for each item of a top-level array, and `(key, value)`
    for any other value, so a multi-gigabyte array is never held in memory.
    A single item or value larger than `max_value_chars` is treated as an error.
    """
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        s = _Stream(f, chunk_size, max_value_chars)
        s.expect("{")
        while True:
            ch = s.peek()
            if ch == "}":
                return
            if ch == ",":
                s.pos += 1
                continue
            if ch == "":
                raise ValueError("unexpected end of file")
            key = s.value(decoder)
            s.expect(":")
            if s.peek() != "[":
                yield key, s.value(decoder)
                continue
            s.pos += 1
            while True:
                ch = s.peek()
                if ch == "]":
                    s.pos += 1
                    break
                if ch == ",":
                    s.pos += 1
                    continue
                if ch == "":
                    raise ValueError("unexpected end of file")
                yield key, s.value(decoder)


# ------------------------------------------------------------------- GSR


@dataclass(frozen=True, slots=True)
class GsrObject:
    """One annotated person in one frame."""

    frame: int  # 1-based, as in the file names and BAS `frame`
    track_id: int
    role: str  # player, goalkeeper, referee, ...
    side: str | None  # "left" / "right" (None for referees)
    jersey: str | None
    x_st: float  # SoccerTrack metres, origin at the centre spot
    y_st: float
    box: tuple[float, float, float, float] | None  # image x, y, w, h (approximate)

    @property
    def label(self) -> str:
        """How the demo names them: by side and number, never by name."""
        side = (self.side or "?").capitalize()
        return f"{side} #{self.jersey}" if self.jersey else f"{side} {self.role}"


_FRAME_RE = re.compile(r"(\d+)\.\w+$")


def _frame_of(image: dict) -> int:
    m = _FRAME_RE.search(str(image.get("file_name", "")))
    if not m:
        raise ValueError(f"image {image.get('image_id')!r} has no frame number in its file name")
    return int(m.group(1))


def _parse_object(ann: dict, frame: int) -> GsrObject | None:
    pitch = ann.get("bbox_pitch") or {}
    if "x_bottom_middle" not in pitch:
        return None
    attrs = ann.get("attributes") or {}
    side = attrs.get("team")
    jersey = attrs.get("jersey")
    bi = ann.get("bbox_image")
    box = (float(bi["x"]), float(bi["y"]), float(bi["w"]), float(bi["h"])) if bi else None
    return GsrObject(
        frame=frame,
        track_id=int(ann.get("track_id", -1)),
        role=str(attrs.get("role", "unknown")),
        side=side if side in ("left", "right") else None,
        jersey=str(jersey) if jersey not in (None, "") else None,
        x_st=float(pitch["x_bottom_middle"]),
        y_st=float(pitch["y_bottom_middle"]),
        box=box,
    )


def iter_gsr(
    path: str | Path,
    first_frame: int = 1,
    last_frame: int | None = None,
    stride: int = 1,
) -> Iterator[GsrObject]:
    """Stream the people annotated in frames `first_frame..last_frame`.

    `stride` keeps every n-th frame counted from `first_frame`. Annotations are
    grouped by frame in order, so reading stops after `last_frame`; a frame out
    of order raises rather than being silently missed.
    """
    frames: dict[str, int] = {}
    newest = 0
    for key, item in iter_top_level(path):
        if key == "images":
            frames[str(item["image_id"])] = _frame_of(item)
        elif key == "annotations":
            if item.get("supercategory") != "object":
                continue
            image_id = str(item["image_id"])
            if image_id not in frames:
                raise ValueError(f"annotation for unknown image {image_id!r} (images must come first)")
            frame = frames[image_id]
            if frame < newest:
                raise ValueError(f"frame {frame} appears after frame {newest}; the file isn't in order")
            newest = frame
            if last_frame is not None and frame > last_frame:
                return
            if frame < first_frame or (frame - first_frame) % stride:
                continue
            obj = _parse_object(item, frame)
            if obj is not None:
                yield obj


# ------------------------------------------------------------------- BAS


# BAS class -> (our type, extra fields we'd expect). See DESIGN.md's table.
BAS_TO_OURS: dict[str, tuple[str, dict[str, str]]] = {
    "PASS": ("pass", {"height": "ground"}),
    "HIGH PASS": ("pass", {"height": "high"}),
    "CROSS": ("pass", {"kind": "cross"}),
    "THROW IN": ("pass", {"kind": "throw_in"}),
    "FREE KICK": ("pass", {"kind": "free_kick"}),
    "OUT": ("pass", {"outcome": "out"}),
    "DRIVE": ("carry", {}),
    "SHOT": ("shot", {}),
    "GOAL": ("shot", {"outcome": "goal"}),
    "HEADER": ("shot", {"body_part": "head"}),
    "BALL PLAYER BLOCK": ("interception", {}),
    "PLAYER SUCCESSFUL TACKLE": ("tackle", {"outcome": "won"}),
}


@dataclass(frozen=True, slots=True)
class BasEvent:
    period: int
    t: float  # seconds since the half's video started
    frame: int | None
    label: str
    side: str | None
    our_type: str


_GAME_TIME = re.compile(r"^\s*(\d)\s*-\s*(\d+):(\d{2})\s*$")


def parse_bas(data: dict, first_half_s: float | None = None) -> list[BasEvent]:
    """BAS actions as events with time in seconds since their half started.

    SoccerTrack's docs say `position` (ms) counts from the start of the match
    for second-half events. This file says it counts from the half's own video,
    so it is only corrected when it is clearly match time: more than a minute
    ahead of the half's `gameTime`. Correcting needs `first_half_s`.
    """
    out: list[BasEvent] = []
    for a in data.get("actions", []):
        m = _GAME_TIME.match(str(a.get("gameTime", "")))
        if not m:
            raise ValueError(f"bad gameTime {a.get('gameTime')!r}")
        period = int(m.group(1))
        game_s = int(m.group(2)) * 60 + int(m.group(3))
        t = float(a["position"]) / 1000
        if period == 2 and t > game_s + 60:
            if first_half_s is None:
                raise ValueError("second-half positions count from kickoff; pass first_half_s")
            t -= first_half_s
        label = str(a["label"]).upper()
        if label not in BAS_TO_OURS:
            raise ValueError(f"unknown BAS class {label!r}")
        side = a.get("team")
        out.append(BasEvent(
            period=period,
            t=t,
            frame=int(a["frame"]) if a.get("frame") is not None else None,
            label=label,
            side=side if side in ("left", "right") else None,
            our_type=BAS_TO_OURS[label][0],
        ))
    return out


def load_bas(path: str | Path, first_half_s: float | None = None) -> list[BasEvent]:
    with open(path, encoding="utf-8") as f:
        return parse_bas(json.load(f), first_half_s)
