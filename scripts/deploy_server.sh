#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${1:?repo url is required}"
BRANCH="${2:?branch is required}"
TARGET_SHA="${3:?target sha is required}"

APP_DIR="${APP_DIR:-/opt/qq-rolebot}"
PYTHON="${PYTHON:-/opt/miniconda3/envs/qq-rolebot/bin/python}"
SERVICE="${SERVICE:-qq-rolebot.service}"

timestamp() {
  date +%Y%m%d%H%M%S
}

require_safe_app_dir() {
  if [[ "$APP_DIR" != "/opt/qq-rolebot" ]]; then
    echo "Refusing to deploy to unexpected APP_DIR=$APP_DIR" >&2
    exit 1
  fi
}

restore_runtime_files() {
  local backup_dir="$1"

  if [[ -f "$backup_dir/.env" && ! -f "$APP_DIR/.env" ]]; then
    cp "$backup_dir/.env" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env" || true
  fi

  if [[ -d "$backup_dir/data" && ! -d "$APP_DIR/data" ]]; then
    mv "$backup_dir/data" "$APP_DIR/data"
  fi

  mkdir -p "$APP_DIR/data"
}

checkout_code() {
  require_safe_app_dir

  if [[ -d "$APP_DIR/.git" ]]; then
    cd "$APP_DIR"
    git reset --hard
    git clean -fd -e .env -e data/ -e voice_refs/ -e voice_cache/ -e models/
    git remote set-url origin "$REPO_URL"
    git fetch --prune origin "$BRANCH"
    git checkout -B "$BRANCH" "origin/$BRANCH"
    git reset --hard "$TARGET_SHA"
    git clean -fd -e .env -e data/ -e voice_refs/ -e voice_cache/ -e models/
    return
  fi

  local backup_dir="/opt/qq-rolebot.pre-git-$(timestamp)"
  if [[ -e "$APP_DIR" ]]; then
    mv "$APP_DIR" "$backup_dir"
  fi

  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
  if ! git cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null; then
    git fetch origin "$BRANCH"
  fi
  git reset --hard "$TARGET_SHA"

  if [[ -d "$backup_dir" ]]; then
    restore_runtime_files "$backup_dir"
  else
    mkdir -p "$APP_DIR/data"
  fi
}

install_and_test() {
  cd "$APP_DIR"
  "$PYTHON" -m pip install -e ".[dev]"
  "$PYTHON" -m ruff check .
  "$PYTHON" -m pytest -q
}

restart_service() {
  systemctl restart "$SERVICE"
  systemctl is-active "$SERVICE"
  journalctl -u "$SERVICE" -n 40 --no-pager
}

main() {
  checkout_code
  install_and_test
  restart_service
}

main "$@"
