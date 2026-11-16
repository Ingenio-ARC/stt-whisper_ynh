#!/bin/bash
# Simulates the full app install locally: mocked ynh_* helpers + fake heavy deps.
set -e
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SIM="${SIM_DIR:-$REPO/../../stt-whisper.sim}"
rm -rf "$SIM"
mkdir -p "$SIM/conf" "$SIM/cache"
export YNH_SIM_SETTINGS="$SIM/settings.sim"
export YNH_SIM_PORT=${SIMPORT:-9800}
export YNH_APP_INSTANCE_NAME="stt-whisper"
export YNH_APP_ARG_DOMAIN="sim.local"
export YNH_APP_ARG_PATH="/stt"
export YNH_APP_ARG_IS_PUBLIC="1"
export YNH_APP_ARG_ALLOWED_IPS="127.0.0.1,::1"
export YNH_APP_ARG_API_KEY=""
export YNH_APP_ARG_MODEL="base"
export YNH_APP_ARG_LANGUAGE="auto"
export YNH_APP_BASEDIR="$REPO"

# export mock helpers into the install subshell
source "$REPO/tests/local_sim/mocks/yunohost/helpers.sh"
for f in $(declare -F | awk '{print $3}'); do export -f "$f"; done

echo "install_dir=$SIM" > "$YNH_SIM_SETTINGS"
echo "domain=sim.local" >> "$YNH_SIM_SETTINGS"
echo "path=/stt" >> "$YNH_SIM_SETTINGS"

export PATH="$REPO/tests/local_sim/mocks/bin:$PATH"
export YNH_SIM_INSTALL_DIR="x"   # avoid warnings
bash "$REPO/scripts/install" || true

echo "=== settings.sim ==="; cat "$YNH_SIM_SETTINGS"
echo "=== staged files ==="; find "$SIM" -maxdepth 3 | sort
echo "=== config.yml generado ==="; cat "$SIM/config.yml" 2>/dev/null
