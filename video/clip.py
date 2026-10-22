"""The clip the video path processes, and where its files live.

Match 117093, first half, 38:00.0 to 39:40.0 (100 s): Left's attack that ends
in their second goal. In those 100 s the BAS events have three crosses, a free
kick, a shot, three outs, a throw-in and the goal (39:35), plus passes and
drives. Chosen 22 Oct from the BAS events (see docs/DESIGN.md, "Video path").
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # the pure-Python pitch_insights.video package

MATCH = "117093"
MATCH_ID = f"ST-{MATCH}"
FPS = 25
FIRST_FRAME = 57001  # 1-based, as in GSR file names and BAS `frame`: 38:00.0
LAST_FRAME = 59500  # 39:39.96
STRIDE = 5  # 5 frames a second
CALIB_STRIDE = 125  # one calibration frame every 5 s, from before the clip only

SOURCE = ROOT / "data" / "soccertrack" / MATCH
VIDEO = SOURCE / f"{MATCH}_panorama_1st_half.mp4"
GSR = SOURCE / f"{MATCH}_1st.json"
BAS = SOURCE / f"{MATCH}_12_class_events.json"

WORK = ROOT / "data" / "video" / MATCH  # git-ignored intermediate files
GSR_CLIP = WORK / "gsr_clip.jsonl"
CALIB_PAIRS = WORK / "calib_pairs.json"
DETECTIONS = WORK / "detections.jsonl"

DETECTIONS_CALIB = WORK / "detections_calib.jsonl"

SAMPLES = ROOT / "samples"  # small outputs kept in git
STEM = f"video-{MATCH}-38min"
CALIBRATION = SAMPLES / f"{STEM}.calibration.json"
FRAMES_OUT = SAMPLES / f"{STEM}.frames.jsonl"
EVENTS_OUT = SAMPLES / f"{STEM}.events.jsonl"
BENCHMARK = SAMPLES / f"{STEM}.benchmark.json"

PERSON_MIN_SCORE = 0.3
BALL_MIN_SCORE = 0.2


def clip_frames() -> range:
    return range(FIRST_FRAME, LAST_FRAME + 1, STRIDE)


def frame_t(frame: int) -> float:
    """Seconds since the half's video started, for a 1-based frame number."""
    return (frame - 1) / FPS
