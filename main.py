"""ma_nfc_jukebox entry point.

Connects to Music Assistant and serves the web UI on port 9015 (Quart +
Hypercorn). Designed to run as a Home Assistant add-on via run.sh, and
directly for development.
"""

import asyncio
import logging

from config import LOG_LEVEL, SERVER, VERSION
from logging_config import setup_logging
from server import Controller, create_app

logger = logging.getLogger("ma_nfc_jukebox")


async def _run():
    setup_logging(LOG_LEVEL)
    logger.info("=== ma_nfc_jukebox version %s ===", VERSION)

    from music_assistant import MusicAssistant
    ma = MusicAssistant()
    await ma.connect()

    controller = Controller(ma=ma)
    app = create_app(controller)

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    config = Config()
    config.bind = [f"{SERVER['host']}:{SERVER['port']}"]
    config.use_reloader = False
    config.graceful_timeout = 2
    logger.info("Serving ma_nfc_jukebox on %s:%d", SERVER["host"], SERVER["port"])

    try:
        await serve(app, config)
    finally:
        await ma.disconnect()


def main():
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
