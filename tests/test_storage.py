from pathlib import Path

import pytest

from qq_rolebot.storage import GroupSettings, MessageRecord, Storage


@pytest.mark.asyncio
async def test_group_settings_default_and_update(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.init()

    settings = await storage.get_group_settings(123)
    assert settings == GroupSettings(
        group_id=123,
        enabled=False,
        random_probability=8,
        muted_until=0,
    )

    await storage.set_group_enabled(123, True)
    await storage.set_random_probability(123, 12)
    await storage.set_muted_until(123, 999)

    settings = await storage.get_group_settings(123)
    assert settings.enabled is True
    assert settings.random_probability == 12
    assert settings.muted_until == 999


@pytest.mark.asyncio
async def test_message_context_is_pruned(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_limit=3)
    await storage.init()

    for index in range(5):
        await storage.save_message(
            MessageRecord(
                group_id=123,
                user_id=456,
                nickname=f"user-{index}",
                text=f"message-{index}",
                created_at=index,
            )
        )

    messages = await storage.recent_messages(123)
    assert [message.text for message in messages] == ["message-2", "message-3", "message-4"]


@pytest.mark.asyncio
async def test_clear_group_context(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.init()

    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="hello", created_at=1)
    )
    await storage.clear_context(123)

    assert await storage.recent_messages(123) == []
