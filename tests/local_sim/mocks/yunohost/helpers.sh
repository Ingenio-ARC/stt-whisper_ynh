#!/bin/bash
# Minimal Yunohost helpers shim for LOCAL SIMULATION ONLY (never in production)
YNH_SIM_SETTINGS="${YNH_SIM_SETTINGS:-$PWD/settings.sim}"
ynh_abort_if_errors() { :; }
ynh_script_progression() { echo "  [sim] ${*}"; }
ynh_print_info() { echo "  [sim] ${*}"; }
ynh_die() { echo "  [sim] DIE: ${*}" >&2; exit 1; }
ynh_find_port() { echo "${YNH_SIM_PORT:-9800}"; }
ynh_app_setting_get() {
  local k=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --key=*) k="${1#--key=}" ;;
      --key) shift; k="$1" ;;
    esac
    shift
  done
  grep -E "^${k}=" "$YNH_SIM_SETTINGS" 2>/dev/null | head -n1 | cut -d= -f2-
}
ynh_app_setting_set() {
  local k="" v=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --key=*) k="${1#--key=}" ;;
      --key) shift; k="$1" ;;
      --value=*) v="${1#--value=}" ;;
      --value) shift; v="$1" ;;
    esac
    shift
  done
  grep -vE "^${k}=" "$YNH_SIM_SETTINGS" > "$YNH_SIM_SETTINGS.tmp" 2>/dev/null || true
  echo "${k}=${v}" >> "$YNH_SIM_SETTINGS.tmp"
  mv "$YNH_SIM_SETTINGS.tmp" "$YNH_SIM_SETTINGS"
}
ynh_add_config() {
  local template="" dest=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --template=*) template="${1#--template=}" ;;
      --template) shift; template="$1" ;;
      --destination=*) dest="${1#--destination=}" ;;
      --destination) shift; dest="$1" ;;
    esac
    shift
  done
  template="$(dirname "$0")/../conf/$(basename "$template")"
  cp "$template" "$dest"
  for tok in $(grep -o '__[A-Z_]*__' "$template" | sort -u); do
    name="${tok//__/}"; name=$(echo "$name" | tr "[:upper:]" "[:lower:]")
    val="${!name}"
    sed -i "s|${tok}|${val}|g" "$dest"
  done
}
ynh_add_nginx_config() {
  cp conf/nginx.conf nginx.conf.staged
  for tok in $(grep -o '__[A-Z_]*__' conf/nginx.conf | sort -u); do
    name="${tok//__/}"; name=$(echo "$name" | tr "[:upper:]" "[:lower:]"); val="${!name}"
    sed -i "s|${tok}|${val}|g" nginx.conf.staged
  done
  echo "  [sim] nginx.conf staged"
}
ynh_add_systemd_config() {
  cp conf/systemd.service stt-whisper.service.staged
  for tok in $(grep -o '__[A-Z_]*__' conf/systemd.service | sort -u); do
    name="${tok//__/}"; name=$(echo "$name" | tr "[:upper:]" "[:lower:]"); val="${!name}"
    sed -i "s|${tok}|${val}|g" stt-whisper.service.staged
  done
  echo "  [sim] systemd staged"
}
ynh_systemd_action() { echo "  [sim] systemd action: $*"; }
ynh_permission_update() { echo "  [sim] permission update: $*"; }
ynh_safe_rm() { rm -rf "$@"; }
