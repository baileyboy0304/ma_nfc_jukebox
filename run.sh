#!/bin/bash
# ma_nfc_jukebox - Home Assistant add-on entrypoint.
# Configuration is read directly from /data/options.json by config.py (single
# config path). Here we only set persistent storage locations and exec the app.

set -e

echo "============================================"
echo "  ma_nfc_jukebox - HA Add-on Starting"
echo "============================================"

export MNJ_OPTIONS_FILE="/data/options.json"
export MNJ_LOGS_DIR="/config/logs"
export PYTHONUNBUFFERED=1

mkdir -p "$MNJ_LOGS_DIR"

exec python3 main.py
