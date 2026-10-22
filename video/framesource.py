"""Reading chosen frames from the half's video, in order, without decoding what isn't needed."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

import cv2
import numpy as np

CLOSE_AHEAD = 50  # frames: decoding forwards is cheaper than seeking, and exact


def read_frames(video: str | Path, frames: Iterable[int]) -> Iterator[tuple[int, np.ndarray]]:
    """Yield `(frame, bgr image)` for 1-based frame numbers.

    Seeking by frame index is exact for this video (checked: a seek and a decode of the same frame
    are identical). Frames given in increasing order that are close together are decoded forwards
    instead of seeking."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"can't open {video}")
    try:
        position = -1  # 0-based index of the frame `read` returns next, once known
        for frame in frames:
            index = frame - 1
            if 0 <= index - position <= CLOSE_AHEAD:
                while position < index:
                    cap.grab()
                    position += 1
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                position = index
            ok, bgr = cap.read()
            position += 1
            if not ok:
                raise RuntimeError(f"can't read frame {frame}")
            yield frame, bgr
    finally:
        cap.release()
