#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${1:?repo url is required}"
BRANCH="${2:?branch is required}"
TARGET_SHA="${3:?target sha is required}"

APP_DIR="${APP_DIR:-/opt/qq-rolebot}"
PYTHON="${PYTHON:-/opt/miniconda3/envs/qq-rolebot/bin/python}"
SERVICE="${SERVICE:-qq-rolebot.service}"
BOT_HOST="${BOT_HOST:-127.0.0.1}"
BOT_PORT="${BOT_PORT:-8080}"
BOT_READY_TIMEOUT_SECONDS="${BOT_READY_TIMEOUT_SECONDS:-30}"

timestamp() {
  date +%Y%m%d%H%M%S
}

git_network() {
  local attempt
  for attempt in 1 2 3; do
    if git -c http.version=HTTP/1.1 "$@"; then
      return 0
    fi
    if [[ "$attempt" -lt 3 ]]; then
      sleep $((attempt * 5))
    fi
  done
  return 1
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

  if [[ -f "$backup_dir/.watchdog.env" && ! -f "$APP_DIR/.watchdog.env" ]]; then
    cp "$backup_dir/.watchdog.env" "$APP_DIR/.watchdog.env"
    chmod 600 "$APP_DIR/.watchdog.env" || true
  fi

  local runtime_dir
  for runtime_dir in data voice_refs voice_cache models; do
    if [[ -d "$backup_dir/$runtime_dir" && ! -d "$APP_DIR/$runtime_dir" ]]; then
      mv "$backup_dir/$runtime_dir" "$APP_DIR/$runtime_dir"
    fi
  done

  mkdir -p "$APP_DIR/data"
}

deploy_archive() {
  local archive_path="$1"
  require_safe_app_dir

  local backup_dir="/opt/qq-rolebot.pre-archive-$(timestamp)"
  local release_dir="/opt/qq-rolebot.release-$(timestamp)"
  mkdir -p "$release_dir"
  tar -xzf "$archive_path" -C "$release_dir"

  if [[ -e "$APP_DIR" ]]; then
    mv "$APP_DIR" "$backup_dir"
  fi
  mv "$release_dir" "$APP_DIR"

  if [[ -d "$backup_dir" ]]; then
    restore_runtime_files "$backup_dir"
  else
    mkdir -p "$APP_DIR/data"
  fi
}

checkout_code() {
  require_safe_app_dir

  if [[ -f "$REPO_URL" ]]; then
    deploy_archive "$REPO_URL"
    return
  fi

  if [[ -d "$APP_DIR/.git" ]]; then
    cd "$APP_DIR"
    git reset --hard
    git clean -fd -e .env -e .watchdog.env -e data/ -e voice_refs/ -e voice_cache/ -e models/
    git remote set-url origin "$REPO_URL"
    git_network fetch --prune origin "$BRANCH"
    git checkout -B "$BRANCH" "origin/$BRANCH"
    git reset --hard "$TARGET_SHA"
    git clean -fd -e .env -e .watchdog.env -e data/ -e voice_refs/ -e voice_cache/ -e models/
    return
  fi

  local backup_dir="/opt/qq-rolebot.pre-git-$(timestamp)"
  if [[ -e "$APP_DIR" ]]; then
    mv "$APP_DIR" "$backup_dir"
  fi

  git_network clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
  if ! git cat-file -e "$TARGET_SHA^{commit}" 2>/dev/null; then
    git_network fetch origin "$BRANCH"
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

wait_for_bot_port() {
  echo "Waiting for $SERVICE to listen on $BOT_HOST:$BOT_PORT"

  local elapsed=0
  while (( elapsed < BOT_READY_TIMEOUT_SECONDS )); do
    if (echo > "/dev/tcp/$BOT_HOST/$BOT_PORT") >/dev/null 2>&1; then
      echo "$SERVICE is listening on $BOT_HOST:$BOT_PORT"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "$SERVICE did not listen on $BOT_HOST:$BOT_PORT within ${BOT_READY_TIMEOUT_SECONDS}s" >&2
  journalctl -u "$SERVICE" -n 80 --no-pager || true
  return 1
}

restart_service() {
  systemctl restart "$SERVICE"
  systemctl is-active "$SERVICE"
  wait_for_bot_port
  journalctl -u "$SERVICE" -n 40 --no-pager
}

main() {
  checkout_code
  install_and_test
  restart_service
}

main "$@"
