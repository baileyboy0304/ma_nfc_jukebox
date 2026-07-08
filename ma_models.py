"""Lightweight, dependency-free Music Assistant data models.

Kept separate from the MA client (mirrors NewLyricsJukebox's ma_models.py)
so callers that only need the shape of a player's state don't need the
``music_assistant_client`` package installed.
"""

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class PlayerState:
    player_id: str
    name: str
    state: str = "idle"             # "playing" | "paused" | "idle"
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    image_url: Optional[str] = None
    position: float = 0.0           # seconds into the track
    duration_ms: Optional[int] = None
    queue_id: Optional[str] = None
    position_last_updated: float = 0.0

    @property
    def is_playing(self) -> bool:
        return self.state == "playing"


def now() -> float:
    return time.time()
