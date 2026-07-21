#!/usr/bin/env bash
set -Eeuo pipefail

instance="${1:?instance name is required}"
if [[ ! "$instance" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
  echo "Invalid NapCat instance name: $instance" >&2
  exit 1
fi

runtime_root="/root/Napcat-$instance"
env_file="$runtime_root/napcat.env"
qq_binary="$runtime_root/opt/QQ/qq"

if [[ ! -f "$env_file" ]]; then
  echo "Missing NapCat environment file: $env_file" >&2
  exit 1
fi
if [[ ! -x "$qq_binary" ]]; then
  echo "Missing NapCat QQ binary: $qq_binary" >&2
  exit 1
fi

account="$(
  awk -F= '
    $0 !~ /^[[:space:]]*#/ && $1 == "ACCOUNT" {
      sub(/^[^=]*=/, "")
      gsub(/[[:space:]]+$/, "")
      print
      exit
    }
  ' "$env_file"
)"
if [[ ! "$account" =~ ^[0-9]+$ ]]; then
  echo "Missing or invalid ACCOUNT in $env_file" >&2
  exit 1
fi

# QQ/Electron writes profile data under HOME and XDG paths. Isolate them per account so
# concurrent NapCat instances cannot share a login cache or an Electron runtime directory.
export HOME="$runtime_root/home"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_RUNTIME_DIR="$runtime_root/run"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

exec /bin/xvfb-run -a "$qq_binary" --no-sandbox -q "$account"
