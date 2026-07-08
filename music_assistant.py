"""Music Assistant WebSocket client wrapper.

Talks to Music Assistant via the official ``music-assistant-client`` package
(the import is lazy so the rest of the app loads without it). Mirrors the
shape of NewLyricsJukebox's music_assistant.py (connect/disconnect/
list_players/get_player_state) so the two add-ons' MA integration could be
shared later, plus the playback-control methods this app needs that
NewLyricsJukebox doesn't (it only reads player state; this app also starts
playback on guests' behalf).
"""

import asyncio
import logging
from typing import List, Optional

from config import MUSIC_ASSISTANT
from ma_models import PlayerState, now

logger = logging.getLogger(__name__)


def _state_str(value) -> str:
    """MA delivers state as an enum (.value) or a plain string. Normalize."""
    if value is None:
        return "idle"
    val = getattr(value, "value", value)
    return str(val).lower()


class MusicAssistant:
    def __init__(self):
        self._url = MUSIC_ASSISTANT["server_url"]
        self._token = MUSIC_ASSISTANT["token"]
        self.preferred_player_id = MUSIC_ASSISTANT["player_id"] or None
        self._client = None
        self._listen_task = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> bool:
        if not self._url:
            logger.warning("Music Assistant server URL not configured")
            return False
        try:
            from music_assistant_client import MusicAssistantClient
        except ImportError:
            logger.error("music-assistant-client not installed")
            return False
        try:
            self._client = MusicAssistantClient(
                server_url=self._url,
                aiohttp_session=None,
                token=self._token or None,
            )
            await asyncio.wait_for(self._client.connect(), timeout=5.0)
            self._listen_task = asyncio.create_task(self._client.start_listening())
            logger.info("Connected to Music Assistant at %s", self._url)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Music Assistant connection failed: %s", exc)
            self._client = None
            return False

    async def disconnect(self):
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    # -- players ------------------------------------------------------------ #

    def list_players(self) -> List[dict]:
        if not self._client:
            return []
        out = []
        for player in getattr(self._client.players, "players", []):
            if not getattr(player, "enabled", True) or getattr(player, "hide_in_ui", False):
                continue
            out.append({
                "player_id": player.player_id,
                "name": getattr(player, "display_name", None) or player.name,
                "available": bool(getattr(player, "available", True)),
                "powered": getattr(player, "powered", None),
                "volume_level": getattr(player, "volume_level", None),
                "is_playing": _state_str(getattr(player, "playback_state", None)) == "playing",
            })
        return out

    async def get_player_state(self, player_id: str) -> Optional[PlayerState]:
        if not self._client:
            return None
        # get_active_queue() may return either a queue id (str) or a PlayerQueue
        # object depending on the client version. Normalize to (queue, queue_id).
        queue = None
        queue_id = player_id
        try:
            active = await self._client.player_queues.get_active_queue(player_id)
        except Exception:  # noqa: BLE001
            active = None
        if active is not None:
            if hasattr(active, "queue_id"):       # it's a PlayerQueue object
                queue = active
                queue_id = active.queue_id
            else:                                  # it's an id string
                queue_id = active
                try:
                    queue = self._client.player_queues.get(queue_id)
                except Exception:  # noqa: BLE001
                    queue = None

        player = self._client.players.get(queue_id) or self._client.players.get(player_id)
        if player is None:
            return None

        player_state = _state_str(getattr(player, "playback_state", None))
        queue_state = _state_str(getattr(queue, "state", None)) if queue else "idle"
        is_playing = player_state == "playing" or queue_state == "playing"
        state = "playing" if is_playing else ("paused" if "pause" in (player_state, queue_state) else "idle")

        title = artist = album = image_url = None
        duration_ms = None

        current_item = getattr(queue, "current_item", None) if queue else None
        media_item = getattr(current_item, "media_item", None) if current_item else None
        if media_item is not None:
            title = getattr(media_item, "name", None)
            artists = getattr(media_item, "artists", None)
            artist = artists[0].name if artists else getattr(media_item, "artist", None)
            album_obj = getattr(media_item, "album", None)
            album = getattr(album_obj, "name", None) if album_obj else None
        current_media = getattr(player, "current_media", None)
        if current_media is not None:
            title = title or getattr(current_media, "title", None)
            artist = artist or getattr(current_media, "artist", None)
            album = album or getattr(current_media, "album", None)
            image_url = getattr(current_media, "image_url", None)

        if current_item is not None and getattr(current_item, "duration", None):
            duration_ms = int(current_item.duration * 1000)
        elif current_media is not None and getattr(current_media, "duration", None):
            duration_ms = int(current_media.duration * 1000)

        if queue is not None:
            raw = getattr(queue, "corrected_elapsed_time", None) if is_playing \
                else getattr(queue, "elapsed_time", None)
            position = float(raw or 0.0)
        else:
            raw = getattr(player, "corrected_elapsed_time", None) if is_playing \
                else getattr(player, "elapsed_time", None)
            position = float(raw or 0.0)

        try:
            image_url = image_url or self._client.get_media_item_image_url(current_item, size=320)
        except Exception:  # noqa: BLE001
            pass

        return PlayerState(
            player_id=player_id,
            name=getattr(player, "display_name", None) or player.name,
            state=state,
            title=title,
            artist=artist,
            album=album,
            image_url=image_url,
            position=position,
            duration_ms=duration_ms,
            queue_id=queue_id,
            position_last_updated=now(),
        )

    # -- transport ------------------------------------------------------------ #

    async def play(self, player_id: str) -> bool:
        return await self._safe(self._client.players.play, player_id) if self._client else False

    async def pause(self, player_id: str) -> bool:
        return await self._safe(self._client.players.pause, player_id) if self._client else False

    async def next(self, player_id: str) -> bool:
        return await self._safe(self._client.players.next_track, player_id) if self._client else False

    async def previous(self, player_id: str) -> bool:
        return await self._safe(self._client.players.previous_track, player_id) if self._client else False

    async def set_volume(self, player_id: str, volume_percent: int) -> bool:
        if not self._client:
            return False
        return await self._safe(self._client.players.volume_set, player_id, int(volume_percent))

    async def play_media(self, player_id: str, uri: str, start_item: Optional[str] = None) -> bool:
        """Replace the player's queue with the given Music Assistant media uri
        and start playing.

        ``uri`` is a Music Assistant media uri, e.g. ``spotify://playlist/<id>``
        or ``spotify://track/<id>`` -- MA resolves it via whichever Spotify
        provider it has configured, lazily if it isn't already in its library.
        This plays under MA's own Spotify account, not the guest's.
        """
        if not self._client:
            return False
        from music_assistant_models.enums import QueueOption
        try:
            active = await self._client.player_queues.get_active_queue(player_id)
            queue_id = active.queue_id if hasattr(active, "queue_id") else (active or player_id)
        except Exception:  # noqa: BLE001
            queue_id = player_id
        try:
            await self._client.player_queues.play_media(
                queue_id, uri, option=QueueOption.REPLACE, start_item=start_item,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("play_media failed for %s: %s", uri, exc)
            return False

    async def _safe(self, fn, *args) -> bool:
        try:
            await fn(*args)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Music Assistant command failed: %s", exc)
            return False
