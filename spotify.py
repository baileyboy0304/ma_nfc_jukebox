"""Guest-only Spotify integration: OAuth login + playlist/track browsing.

Playback never touches this module. Once a guest picks something to play,
server.py hands the Spotify URI to Music Assistant (music_assistant.py),
which streams it through whichever Spotify provider MA itself is configured
with. This module exists purely so guests can browse THEIR OWN playlists --
ported from the guest-side functions in the original nfc_jukebox/server.py,
with the host/playback-account flow (streaming scope, Premium checks, Web
Playback SDK) removed since MA now owns playback.
"""

import base64
import logging
import secrets
import time
from urllib.parse import urlencode

import requests

from config import REDIRECT_URI, SPOTIFY

logger = logging.getLogger(__name__)

GUEST_PUBLIC_SCOPE = "user-read-private"
GUEST_PRIVATE_SCOPE = "user-read-private playlist-read-private"
STATE_TTL_SECONDS = 10 * 60


def credentials_configured() -> bool:
    return bool(SPOTIFY["client_id"] and SPOTIFY["client_secret"])


def _basic_auth_header():
    raw = f"{SPOTIFY['client_id']}:{SPOTIFY['client_secret']}".encode("utf-8")
    return {"Authorization": f"Basic {base64.b64encode(raw).decode('utf-8')}"}


def _get(access_token, url, params=None):
    response = requests.get(
        url, headers={"Authorization": f"Bearer {access_token}"}, params=params, timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _exchange_code_for_token(code):
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}
    headers = _basic_auth_header()
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    response = requests.post(
        "https://accounts.spotify.com/api/token", data=data, headers=headers, timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _playlist_payload(item, tracks=None):
    images = item.get("images") or []
    image_url = images[0]["url"] if images else ""
    track_info = item.get("tracks") or {}
    is_public = item.get("public")
    if is_public is True:
        public_text = "public"
    elif is_public is False:
        public_text = "private"
    else:
        public_text = "unknown visibility"
    playlist_id = item.get("id") or ""
    return {
        "name": item.get("name") or "Untitled playlist",
        "id": playlist_id,
        "uri": item.get("uri") or (f"spotify:playlist:{playlist_id}" if playlist_id else ""),
        "image": image_url,
        "tracks_total": track_info.get("total", 0),
        "public_text": public_text,
        "tracks": tracks or [],
    }


def _track_payload(item, fallback_image=""):
    track = item.get("track") if "track" in item else item
    if not track or track.get("type") != "track" or not track.get("uri"):
        return None
    album = track.get("album") or {}
    images = album.get("images") or []
    image_url = images[0]["url"] if images else fallback_image
    artists = ", ".join(a.get("name", "") for a in track.get("artists", []) if a.get("name"))
    return {
        "name": track.get("name") or "Untitled track",
        "id": track.get("id") or "",
        "uri": track.get("uri") or "",
        "artists": artists,
        "album": album.get("name") or "",
        "duration_ms": track.get("duration_ms", 0),
        "image": image_url,
    }


def _playlist_tracks(access_token, playlist_id, fallback_image=""):
    tracks = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    params = {
        "limit": 100,
        "offset": 0,
        "fields": "items(track(id,name,uri,type,duration_ms,artists(name),album(name,images))),next",
    }
    while url:
        data = _get(access_token, url, params=params)
        for item in data.get("items", []):
            track = _track_payload(item, fallback_image=fallback_image)
            if track:
                tracks.append(track)
        url = data.get("next")
        params = None
    return tracks


def _current_user_playlists(access_token, mode):
    playlists = []
    url = "https://api.spotify.com/v1/me/playlists"
    params = {"limit": 50, "offset": 0}
    while url:
        data = _get(access_token, url, params=params)
        for item in data.get("items", []):
            playlist = _playlist_payload(item)
            if mode == "public" and playlist["public_text"] == "private":
                continue
            playlist["tracks"] = _playlist_tracks(access_token, playlist["id"], playlist["image"])
            playlists.append(playlist)
        url = data.get("next")
        params = None
    return playlists


def _guest_summary(guest):
    return {
        "id": guest["id"],
        "display_name": guest.get("display_name", ""),
        "user_id": guest.get("user_id", ""),
        "mode": guest.get("mode", ""),
        "created": guest.get("created", 0),
        "playlists": [
            {key: value for key, value in playlist.items() if key != "tracks"}
            for playlist in guest.get("playlists", [])
        ],
    }


class GuestStore:
    """In-memory guest registry: pending OAuth state, connected guests, and
    their shared playlists. Cleared on restart -- matches the original
    prototype's behavior; nothing here is persisted to disk."""

    def __init__(self):
        self._pending_states = {}
        self.guests = {}
        self.guest_order = []
        self.selected_guest_id = ""

    def _cleanup_pending_states(self):
        cutoff = time.time() - STATE_TTL_SECONDS
        expired = [s for s, d in self._pending_states.items() if d.get("created", 0) < cutoff]
        for s in expired:
            self._pending_states.pop(s, None)

    def authorize_url(self, mode="public", return_to="/player"):
        self._cleanup_pending_states()
        scope = GUEST_PRIVATE_SCOPE if mode == "private" else GUEST_PUBLIC_SCOPE
        state = secrets.token_urlsafe(24)
        self._pending_states[state] = {"mode": mode, "created": time.time(), "return_to": return_to}
        params = {
            "response_type": "code",
            "client_id": SPOTIFY["client_id"],
            "scope": scope,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "show_dialog": "true",
        }
        return "https://accounts.spotify.com/authorize?" + urlencode(params)

    def pop_pending_state(self, state):
        self._cleanup_pending_states()
        return self._pending_states.pop(state, None)

    def complete_login(self, code, state_data):
        mode = state_data.get("mode", "public")
        token_data = _exchange_code_for_token(code)
        access_token = token_data["access_token"]
        me = _get(access_token, "https://api.spotify.com/v1/me")
        playlists = _current_user_playlists(access_token, mode)

        user_id = me.get("id") or secrets.token_urlsafe(10)
        display_name = me.get("display_name") or user_id
        guest = {
            "id": user_id,
            "display_name": display_name,
            "user_id": user_id,
            "mode": "Public playlists only" if mode == "public" else "Public and private playlists",
            "created": time.time(),
            "playlists": playlists,
        }
        self.guests[guest["id"]] = guest
        if guest["id"] in self.guest_order:
            self.guest_order.remove(guest["id"])
        self.guest_order.insert(0, guest["id"])
        self.selected_guest_id = guest["id"]
        return guest

    def payload(self):
        ordered = [_guest_summary(self.guests[g]) for g in self.guest_order if g in self.guests]
        selected = self.selected_guest_id if self.selected_guest_id in self.guests \
            else (self.guest_order[0] if self.guest_order else "")
        return {"guests": ordered, "selected_guest_id": selected}

    def delete(self, guest_id):
        self.guests.pop(guest_id, None)
        if guest_id in self.guest_order:
            self.guest_order.remove(guest_id)
        self.selected_guest_id = self.guest_order[0] if self.guest_order else ""
        return self.selected_guest_id

    def get_playlist(self, guest_id, playlist_id):
        guest = self.guests.get(guest_id)
        if not guest:
            return None
        for playlist in guest.get("playlists", []):
            if playlist.get("id") == playlist_id:
                return playlist
        return None
