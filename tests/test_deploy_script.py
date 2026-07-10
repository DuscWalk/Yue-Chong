from pathlib import Path

SCRIPT = Path("scripts/deploy_server.sh")
WORKFLOW = Path(".github/workflows/deploy.yml")


def test_existing_checkout_is_cleaned_before_checkout() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'APP_DIR="${APP_DIR:-/opt/qq-rolebot}"' in script
    assert 'PYTHON="${PYTHON:-/opt/miniconda3/envs/qq-rolebot/bin/python}"' in script

    existing_checkout = script.split('if [[ -d "$APP_DIR/.git" ]]; then', 1)[1].split(
        "return", 1
    )[0]
    reset_index = existing_checkout.index("git reset --hard")
    clean_index = existing_checkout.index("git clean -fd")
    checkout_index = existing_checkout.index("git checkout -B")

    assert reset_index < checkout_index
    assert clean_index < checkout_index


def test_network_git_operations_use_retrying_http1_helper() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "git_network() {" in script
    assert "git -c http.version=HTTP/1.1" in script
    assert 'git_network fetch --prune origin "$BRANCH"' in script
    assert 'git_network clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"' in script


def test_deploy_script_accepts_uploaded_source_archive() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "deploy_archive() {" in script
    assert 'if [[ -f "$REPO_URL" ]]; then' in script
    assert 'tar -xzf "$archive_path"' in script
    assert "for runtime_dir in data voice_refs voice_cache models" in script


def test_deploy_script_preserves_stickers_directory() -> None:
    script = Path("scripts/deploy_server.sh").read_text(encoding="utf-8")

    assert "stickers" in script
    assert "voice_cache models stickers" in script


def test_deploy_script_preserves_watchdog_env() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert (
        'if [[ -f "$backup_dir/.watchdog.env" && ! -f "$APP_DIR/.watchdog.env" ]]; then'
        in script
    )
    assert 'cp "$backup_dir/.watchdog.env" "$APP_DIR/.watchdog.env"' in script
    assert 'chmod 600 "$APP_DIR/.watchdog.env"' in script
    assert "git clean -fd -e .env -e .watchdog.env -e data/" in script


def test_deploy_script_waits_for_bot_port_after_restart() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'BOT_HOST="${BOT_HOST:-127.0.0.1}"' in script
    assert 'BOT_PORT="${BOT_PORT:-8080}"' in script
    assert "wait_for_bot_port() {" in script
    assert 'echo "Waiting for $SERVICE to listen on $BOT_HOST:$BOT_PORT"' in script

    restart_service = script.split("restart_service() {", 1)[1].split("}", 1)[0]
    active_index = restart_service.index('systemctl is-active "$SERVICE"')
    wait_index = restart_service.index("wait_for_bot_port")

    assert active_index < wait_index


def test_github_actions_uploads_archive_instead_of_server_fetching_github() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "Create source archive" in workflow
    assert "qq-rolebot-source-${{ github.sha }}.tar.gz" in workflow
    assert ":/tmp/$SOURCE_ARCHIVE" in workflow
    assert "bash /tmp/qq-rolebot-deploy.sh '/tmp/$SOURCE_ARCHIVE'" in workflow
