from pathlib import Path

SCRIPT = Path("scripts/deploy_server.sh")


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
