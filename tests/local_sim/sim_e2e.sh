#!/bin/bash
# Boots the REAL microservice locally against the simulated install, with fake whisper/ffmpeg.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SIM="${SIM_DIR:-$REPO/../../stt-whisper.sim}"
PORT=${SIMPORT:-9801}

[ -f "$SIM/config.yml" ] || { echo "Run sim_install.sh first"; exit 1; }

# adapt config for local user-space run
sed -e "s|/var/cache/stt-whisper|$SIM/cache|" -e "s|/var/www/stt-whisper|$SIM|" "$SIM/config.yml" > "$SIM/config.e2e.yml"

# bootstrap pip (user) if fastapi missing
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "[e2e] bootstrapping pip + deps (--user)..."
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  python3 /tmp/get-pip.py --user --break-system-packages -q
  python3 -m pip install --user --break-system-packages -q fastapi "uvicorn[standard]" python-multipart pyyaml
fi

cd "$SIM/app"
export PATH="$REPO/tests/local_sim/mocks/bin:$PATH"
export CONFIG_PATH="$SIM/config.e2e.yml"
export PYTHONUSERBASE="$HOME/.local"
mkdir -p "$SIM/cache"

python3 -m uvicorn main:app --host 127.0.0.1 --port "$PORT" > "$SIM/uvicorn.log" 2>&1 &
UV_PORT=$!
sleep 2

KEY=$(grep '^  api_key:' "$SIM/config.yml" | head -n1 | sed 's/.*"\(.*\)".*/\1/')
JFK="${JFK:-$REPO/.test-audio/jfk.wav}"

echo "=== health ==="
curl -s -m 10 -H "X-API-KEY: $KEY" "http://127.0.0.1:$PORT/health"; echo
echo "=== transcribe (fake whisper, JSON) ==="
curl -s -m 30 -H "X-API-KEY: $KEY" -F "file=@$JFK" "http://127.0.0.1:$PORT/transcribe"; echo
echo "=== transcribe/plain ==="
curl -s -m 30 -H "X-API-KEY: $KEY" -F "file=@$JFK" "http://127.0.0.1:$PORT/transcribe/plain"; echo
echo "=== 403 sin key ==="
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@$JFK" "http://127.0.0.1:$PORT/transcribe"

kill $UV_PORT 2>/dev/null || true
tail -n 5 "$SIM/uvicorn.log" || true
