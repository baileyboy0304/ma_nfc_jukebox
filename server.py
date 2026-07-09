"""HTTP server + controller wiring guest Spotify browsing to Music Assistant
playback.

Page routes (``/setup``, ``/join``, ``/login-public``, ``/login-private``,
``/callback``, ``/player``) are unprefixed. JSON action endpoints are
prefixed ``/jukebox/...`` specifically so they don't collide with
NewLyricsJukebox's bare ``/players``, ``/transport``, etc. if the two add-ons
are ever combined under one Quart app.
"""

import logging
from urllib.parse import urlencode

from quart import Quart, jsonify, make_response, redirect, render_template, request

from config import RESOURCES_DIR, SERVER, SPOTIFY_RELAY_URL, VERSION
from spotify import GuestStore, credentials_configured

logger = logging.getLogger(__name__)

GUEST_COOKIE = "mnj_guest"


def _local_base(req) -> str:
    """The add-on's own direct-port base URL, as reachable by a guest on the
    network -- e.g. ``http://192.168.1.129:9016``.

    Home Assistant's ingress proxy forwards the browser's ORIGINAL Host
    header (HA's own port, e.g. :8123) rather than rewriting it to this
    add-on's port, so ``request.host_url`` is only trustworthy when this
    page was loaded directly (never via ingress). Detect ingress via the
    ``X-Ingress-Path`` header Supervisor adds to every proxied request, and
    in that case substitute this add-on's real, fixed port -- the hostname
    portion is still correct either way, only the port is wrong.
    """
    if req.headers.get("X-Ingress-Path"):
        host = req.host.split(":")[0]
        return f"http://{host}:{SERVER['port']}"
    return req.host_url.rstrip("/")


class AppError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _to_ma_uri(spotify_uri: str) -> str:
    """``spotify:playlist:<id>`` -> ``spotify://playlist/<id>`` -- the uri form
    Music Assistant resolves media by, via whichever Spotify provider it has
    configured (not the guest's personal account)."""
    parts = (spotify_uri or "").split(":")
    if len(parts) != 3 or parts[0] != "spotify":
        return spotify_uri
    return f"spotify://{parts[1]}/{parts[2]}"


class Controller:
    def __init__(self, ma):
        self.ma = ma
        self.guests = GuestStore()

    # -- Spotify guest browsing --------------------------------------------- #

    def guests_payload(self):
        return self.guests.payload()

    def get_playlist(self, guest_id, playlist_id):
        return self.guests.get_playlist(guest_id, playlist_id)

    def delete_guest(self, guest_id):
        return self.guests.delete(guest_id)

    # -- Music Assistant playback -------------------------------------------- #

    def devices_payload(self):
        return {
            "connected": self.ma.connected,
            "players": self.ma.list_players(),
            "preferred_player_id": self.ma.preferred_player_id,
        }

    async def playback_state(self, player_id):
        if not player_id or not self.ma.connected:
            return {"has_playback": False}
        state = await self.ma.get_player_state(player_id)
        if state is None:
            return {"has_playback": False}
        return {
            "has_playback": True,
            "is_playing": state.is_playing,
            "progress_ms": int(state.position * 1000),
            "duration_ms": state.duration_ms or 0,
            "name": state.title or "",
            "artists": state.artist or "",
            "image": state.image_url or "",
            "player_id": state.player_id,
            "player_name": state.name,
        }

    async def play(self, player_id, context_uri="", track_uri=""):
        if not player_id:
            raise AppError("Wait for Music Assistant or choose a speaker.", 400)
        if not context_uri and not track_uri:
            raise AppError("Choose something to play.", 400)
        if context_uri and not context_uri.startswith("spotify:playlist:"):
            raise AppError("Only playlist playback is supported from shared guests.", 400)
        if track_uri and not track_uri.startswith("spotify:track:"):
            raise AppError("Choose a playable track.", 400)
        if not self.ma.connected:
            raise AppError("Music Assistant is not connected.", 503)

        # Tapping a track inside a playlist plays the PLAYLIST starting at that
        # track, so the rest of the playlist continues in the queue. Music
        # Assistant matches the start item by the bare provider item id (the
        # Spotify track id), not a full uri. Tapping the "Play playlist" button
        # sends only the playlist (start from the top); a bare track with no
        # playlist context just plays that track.
        if context_uri and track_uri:
            media = _to_ma_uri(context_uri)
            start_item = track_uri.split(":")[-1]      # spotify:track:<id> -> <id>
        elif track_uri:
            media = _to_ma_uri(track_uri)
            start_item = None
        else:
            media = _to_ma_uri(context_uri)
            start_item = None

        error = await self.ma.play_media(player_id, media, start_item=start_item)
        if error:
            # Playback runs through Music Assistant's OWN Spotify account, so a
            # guest playlist/track that account can't see resolves to zero tracks.
            if "no playable items" in error.lower():
                error = (
                    "The house music system can't access this. "
                    "It may be private -- ask the guest to make it public, or pick something else."
                )
            raise AppError(error, 502)
        return {"ok": True}

    async def transport(self, action, player_id):
        if action not in ("next", "previous", "pause", "resume"):
            raise AppError("Unknown playback command.", 400)
        if not player_id:
            raise AppError("Choose a speaker first.", 400)
        if not self.ma.connected:
            raise AppError("Music Assistant is not connected.", 503)
        fn = {
            "next": self.ma.next, "previous": self.ma.previous,
            "pause": self.ma.pause, "resume": self.ma.play,
        }[action]
        error = await fn(player_id)
        if error:
            raise AppError(error, 502)
        return {"ok": True}

    async def set_volume(self, player_id, volume_percent):
        if not player_id:
            raise AppError("Choose a speaker first.", 400)
        if not self.ma.connected:
            raise AppError("Music Assistant is not connected.", 503)
        try:
            volume = max(0, min(100, int(volume_percent)))
        except (TypeError, ValueError):
            raise AppError("Choose a valid volume.", 400)
        error = await self.ma.set_volume(player_id, volume)
        if error:
            raise AppError(error, 502)
        return {"ok": True}


def create_app(controller: Controller) -> Quart:
    app = Quart(
        __name__,
        template_folder=str(RESOURCES_DIR / "templates"),
        static_folder=str(RESOURCES_DIR),
        static_url_path="/static",
    )

    # -- pages --------------------------------------------------------------- #

    @app.route("/")
    async def index():
        # The default sidebar/ingress landing page -- guests never see this
        # (they always arrive via /join on the direct port).
        return redirect("player")

    @app.route("/setup")
    async def setup():
        local_base = _local_base(request)
        return await render_template(
            "setup.html", version=VERSION, join_url=f"{local_base}/join",
            redirect_uri=SPOTIFY_RELAY_URL,
        )

    @app.route("/join")
    async def join():
        cookie_guest = request.cookies.get(GUEST_COOKIE, "")
        if cookie_guest in controller.guests.guests:
            return redirect("player?" + urlencode({"guest": cookie_guest}))
        if not credentials_configured():
            return await render_template("join_error.html", version=VERSION)
        return await render_template("join.html", version=VERSION)

    @app.route("/login-public")
    async def login_public():
        return _start_guest_login(controller, "public", _local_base(request))

    @app.route("/login-private")
    async def login_private():
        return _start_guest_login(controller, "private", _local_base(request))

    @app.route("/callback")
    async def callback():
        args = request.args
        state_data = controller.guests.pop_pending_state(args.get("state", ""))
        return_to = (state_data or {}).get("return_to", "player")

        if "error" in args or not state_data or not args.get("code"):
            return redirect("join")

        try:
            guest = controller.guests.complete_login(args.get("code"), state_data)
        except Exception:
            logger.exception("Guest Spotify login failed")
            return redirect("join")

        resp = redirect(return_to + "?" + urlencode({"guest": guest["id"]}))
        resp.set_cookie(GUEST_COOKIE, guest["id"], max_age=2592000, samesite="Lax")
        return resp

    @app.route("/player")
    @app.route("/screen")
    async def player():
        guest_id = request.args.get("guest", "")
        html = await render_template("player.html", version=VERSION)
        resp = await make_response(html)
        if guest_id in controller.guests.guests:
            resp.set_cookie(GUEST_COOKIE, guest_id, max_age=2592000, samesite="Lax")
        return resp

    # -- JSON action endpoints ------------------------------------------------ #

    @app.route("/jukebox/status")
    async def status():
        return jsonify({"connected": controller.ma.connected})

    @app.route("/jukebox/guests")
    async def guests():
        return jsonify(controller.guests_payload())

    @app.route("/jukebox/tracks")
    async def tracks():
        playlist = controller.get_playlist(
            request.args.get("guest_id", ""), request.args.get("playlist_id", ""),
        )
        if playlist is None:
            return jsonify({"error": "Playlist not found."}), 404
        return jsonify({"playlist": playlist})

    @app.route("/jukebox/delete-guest", methods=["POST"])
    async def delete_guest():
        body = await request.get_json(silent=True) or {}
        selected = controller.delete_guest(body.get("guest_id", ""))
        return jsonify({"ok": True, "selected_guest_id": selected})

    @app.route("/jukebox/devices")
    async def devices():
        return jsonify(controller.devices_payload())

    @app.route("/jukebox/playback-state")
    async def playback_state():
        return jsonify(await controller.playback_state(request.args.get("player_id", "")))

    @app.route("/jukebox/play", methods=["POST"])
    async def play():
        body = await request.get_json(silent=True) or {}
        try:
            result = await controller.play(
                body.get("player_id", ""), body.get("context_uri", ""), body.get("track_uri", ""),
            )
            return jsonify(result)
        except AppError as e:
            return jsonify({"error": e.message}), e.status_code

    @app.route("/jukebox/transport", methods=["POST"])
    async def transport():
        body = await request.get_json(silent=True) or {}
        try:
            result = await controller.transport(body.get("action", ""), body.get("player_id", ""))
            return jsonify(result)
        except AppError as e:
            return jsonify({"error": e.message}), e.status_code

    @app.route("/jukebox/volume", methods=["POST"])
    async def volume():
        body = await request.get_json(silent=True) or {}
        try:
            result = await controller.set_volume(body.get("player_id", ""), body.get("volume_percent", 70))
            return jsonify(result)
        except AppError as e:
            return jsonify({"error": e.message}), e.status_code

    @app.after_request
    async def cache_headers(response):
        if request.path.startswith("/jukebox/") or request.path in ("/setup", "/join", "/player", "/screen"):
            response.headers["Cache-Control"] = "no-store"
        elif request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app


def _start_guest_login(controller: Controller, mode: str, local_base: str):
    if not credentials_configured():
        return redirect("join")
    url = controller.guests.authorize_url(local_base, mode=mode, return_to="player")
    return redirect(url)
