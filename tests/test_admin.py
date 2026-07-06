from pathlib import Path

import pytest

from qq_rolebot.admin import handle_admin_command, is_admin_command, parse_duration_seconds
from qq_rolebot.config import load_settings
from qq_rolebot.storage import Storage


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika",
        "SENSITIVE_WORDS": "",
    }


def test_is_admin_command() -> None:
    assert is_admin_command("/bot on") is True
    assert is_admin_command(" /bot status ") is True
    assert is_admin_command("hello") is False


def test_parse_duration_seconds() -> None:
    assert parse_duration_seconds("10m") == 600
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("30s") == 30


@pytest.mark.asyncio
async def test_admin_on_off_status(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()

    assert await handle_admin_command(
        "/bot on", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    ) == "bot enabled"
    assert (await storage.get_group_settings(20)).enabled is True

    status = await handle_admin_command(
        "/bot status", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    )
    assert "enabled=True" in status

    assert await handle_admin_command(
        "/bot off", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    ) == "bot disabled"
    assert (await storage.get_group_settings(20)).enabled is False


@pytest.mark.asyncio
async def test_unauthorized_admin_command_is_silent(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()

    result = await handle_admin_command(
        "/bot on", sender_id=99, group_id=20, now=100, settings=settings, storage=storage
    )

    assert result is None
