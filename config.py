"""Single source of configuration for ma_nfc_jukebox.

Precedence: Home Assistant add-on options (``/data/options.json``) -> environment
variables -> hardcoded defaults. Mirrors NewLyricsJukebox's config.py so the
Music Assistant option keys shared between the two add-ons are drop-in
compatible if they're ever combined.
"""

import json
import os
from pathlib import Path

OPTIONS_FILE = os.getenv("MNJ_OPTIONS_FILE", "/data/options.json")

try:
    with open(OPTIONS_FILE, "r", encoding="utf-8") as fh:
        _OPTIONS = json.load(fh) or {}
except (OSError, ValueError):
    _OPTIONS = {}


def _read_version() -> str:
    """Read the add-on version from config.yaml (shipped in the image) so we can
    log which build is actually running. Avoids a yaml dependency."""
    try:
        for line in (Path(__file__).parent / "config.yaml").read_text().splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "unknown"


VERSION = _read_version()


def conf(key, default=None):
    """Resolve a config value: options.json -> env var -> default.

    ``key`` may be dotted (e.g. ``system.music_assistant.token``). The dotted
    form is mapped to an UPPER_SNAKE env var; for options.json the dotted key,
    then its final segment, are tried.
    """
    if key in _OPTIONS and _OPTIONS[key] not in (None, ""):
        return _OPTIONS[key]
    last = key.split(".")[-1]
    if last in _OPTIONS and _OPTIONS[last] not in (None, ""):
        return _OPTIONS[last]

    env_val = os.getenv(key.upper().replace(".", "_"))
    if env_val is not None and env_val.strip():
        return env_val
    return default


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


RESOURCES_DIR = Path(__file__).parent / "resources"

# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #

# Fixed at 9015 to match the add-on's ingress_port and container port in
# config.yaml (same reasoning as NewLyricsJukebox's 9014 -- ingress_port is
# static YAML and can't follow an option). Env override is for local dev only.
SERVER = {
    "host": conf("server_host", "0.0.0.0"),
    "port": _as_int(os.getenv("SERVER_PORT", "9015"), 9015),
}

LOG_LEVEL = conf("log_level", "INFO")

# --------------------------------------------------------------------------- #
# Guest access / OAuth callback
# --------------------------------------------------------------------------- #

# Spotify only allows plain "http://" redirect URIs for the 127.0.0.1 loopback
# address -- everything else must be HTTPS, which this add-on (running on a
# plain LAN address) doesn't have. We route the OAuth callback through
# SPOTIFY_RELAY_URL, a small static page hosted on GitHub Pages whose only
# job is to bounce the guest's browser back down to the local address it
# reached this add-on through (see docs/callback/index.html). This mirrors
# the same trick Music Assistant's own Spotify provider setup uses -- zero
# configuration, but the guest's phone must be on the same network as this
# add-on at login time.
SPOTIFY_RELAY_URL = "https://baileyboy0304.github.io/ma_nfc_jukebox/callback/"

# --------------------------------------------------------------------------- #
# Music Assistant (same keys as NewLyricsJukebox's config.py)
# --------------------------------------------------------------------------- #

MUSIC_ASSISTANT = {
    "server_url": conf("music_assistant_base_url", "") or conf("system.music_assistant.server_url", ""),
    "token": conf("music_assistant_token", "") or conf("system.music_assistant.token", ""),
    "player_id": conf("music_assistant_player_id", "") or conf("system.music_assistant.player_id", ""),
}

# --------------------------------------------------------------------------- #
# Spotify (guest login only -- playback runs through Music Assistant)
# --------------------------------------------------------------------------- #

SPOTIFY = {
    "client_id": (conf("spotify_client_id", "") or "").strip(),
    "client_secret": (conf("spotify_client_secret", "") or "").strip(),
}
