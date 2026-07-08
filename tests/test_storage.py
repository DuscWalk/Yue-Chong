from pathlib import Path

import pytest

from qq_rolebot.storage import GroupSettings, MessageRecord, Storage, VisionContextRecord


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
async def test_recent_messages_respects_context_window(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_window_seconds=600)
    await storage.init()

    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="old", created_at=399)
    )
    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="fresh", created_at=400)
    )
    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="now", created_at=1000)
    )

    messages = await storage.recent_messages(123, now=1000)

    assert [message.text for message in messages] == ["fresh", "now"]


@pytest.mark.asyncio
async def test_recent_messages_excludes_future_messages(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_window_seconds=600)
    await storage.init()

    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="now", created_at=1000)
    )
    await storage.save_message(
        MessageRecord(
            group_id=123,
            user_id=456,
            nickname="amy",
            text="future",
            created_at=1001,
        )
    )

    messages = await storage.recent_messages(123, now=1000)

    assert [message.text for message in messages] == ["now"]


@pytest.mark.asyncio
async def test_clear_group_context(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.init()

    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="hello", created_at=1)
    )
    await storage.clear_context(123)

    assert await storage.recent_messages(123) == []


@pytest.mark.asyncio
async def test_vision_context_can_be_found_by_media_marker(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_window_seconds=600)
    await storage.init()

    await storage.save_vision_context(
        VisionContextRecord(
            group_id=123,
            media_marker="[image: quoted.png]",
            summary="纯视觉描述：这是夕。",
            created_at=100,
        )
    )

    record = await storage.find_vision_context(
        123,
        media_markers=["[image: quoted.png]"],
        now=120,
    )

    assert record is not None
    assert record.summary == "纯视觉描述：这是夕。"


@pytest.mark.asyncio
async def test_vision_context_falls_back_to_latest_recent_image(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_window_seconds=600)
    await storage.init()

    await storage.save_vision_context(
        VisionContextRecord(
            group_id=123,
            media_marker="[image: old.png]",
            summary="纯视觉描述：旧图。",
            created_at=100,
        )
    )
    await storage.save_vision_context(
        VisionContextRecord(
            group_id=123,
            media_marker="[image: latest.png]",
            summary="纯视觉描述：这是夕。",
            created_at=110,
        )
    )

    record = await storage.find_vision_context(123, media_markers=[], now=120)

    assert record is not None
    assert record.media_marker == "[image: latest.png]"
    assert record.summary == "纯视觉描述：这是夕。"


@pytest.mark.asyncio
async def test_vision_context_respects_context_window(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_window_seconds=10)
    await storage.init()

    await storage.save_vision_context(
        VisionContextRecord(
            group_id=123,
            media_marker="[image: old.png]",
            summary="纯视觉描述：旧图。",
            created_at=100,
        )
    )

    record = await storage.find_vision_context(
        123,
        media_markers=["[image: old.png]"],
        now=111,
    )

    assert record is None
