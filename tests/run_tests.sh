#!/bin/bash
set -e

APP=${1:-stt-whisper}
APP_DIR=/var/www/$APP
VENV=$APP_DIR/venv
CONFIG_PATH=$APP_DIR/config.yml

if [ ! -d "$APP_DIR" ]; then
    echo "App directory not found: $APP_DIR"
    exit 1
fi

export CONFIG_PATH
"$VENV/bin/pytest" "$APP_DIR/app/tests" -v "$@"
