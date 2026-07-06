from pathlib import Path

import pytest

from qq_rolebot.config import load_settings
from qq_rolebot.model_client import ModelResult
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter
from qq_rolebot.service import ChatService
from qq_rolebot.storage import Storage


class FakeModel:
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        assert messages
        return ModelResult(ok=True, text="model reply")


class CapturingModel:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        self.messages = messages
        return ModelResult(ok=True, text="model reply")


class FakeToolRunner:
    def __init__(self, *, direct_reply: str | None = None, context: str = "") -> None:
        self.direct_reply = direct_reply
        self.context = context
        self.calls = 0

    async def run(self, message: IncomingMessage):
        self.calls += 1

        class Result:
            def __init__(self, direct_reply: str | None, context: str) -> None:
                self.direct_reply = direct_reply
                self.context = context

        return Result(self.direct_reply, self.context)


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


def msg(
    text: str,
    *,
    at_bot: bool,
    sender: int = 11,
    group: int = 20,
    created_at: int = 100,
) -> IncomingMessage:
    return IncomingMessage(
        group_id=group,
        user_id=sender,
        nickname="Amy",
        text=text,
        is_at_bot=at_bot,
        created_at=created_at,
    )


def private_msg(text: str, *, sender: int = 99) -> IncomingMessage:
    return IncomingMessage(
        group_id=0,
        user_id=sender,
        nickname="Private Amy",
        text=text,
        is_at_bot=False,
        is_private=True,
        created_at=100,
    )


@pytest.mark.asyncio
async def test_service_handles_admin_command(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("/bot on", at_bot=False, sender=10), random_value=99)

    assert reply == "bot enabled"
    assert (await storage.get_group_settings(20)).enabled is True


@pytest.mark.asyncio
async def test_service_switches_persona_variant_by_admin_command(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    assert "方言人格" in service.persona.profile

    reply = await service.handle(
        msg("/bot persona standard", at_bot=False, sender=10),
        random_value=99,
    )

    assert reply == "persona switched to standard"
    assert "方言人格" not in service.persona.profile

    reply = await service.handle(
        msg("/bot persona dialect", at_bot=False, sender=10),
        random_value=99,
    )

    assert reply == "persona switched to dialect"
    assert "方言人格" in service.persona.profile


@pytest.mark.asyncio
async def test_service_replies_to_mention_when_enabled(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("hello", at_bot=True), random_value=99)

    assert reply == "model reply"


@pytest.mark.asyncio
async def test_service_does_not_rate_limit_direct_mentions(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(group_limit=1, user_cooldown_seconds=100),
    )

    first = await service.handle(msg("first", at_bot=True, created_at=100), random_value=99)
    second = await service.handle(msg("second", at_bot=True, created_at=101), random_value=99)

    assert first == "model reply"
    assert second == "model reply"


@pytest.mark.asyncio
async def test_service_does_not_rate_limit_random_group_replies(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(group_limit=1, user_cooldown_seconds=100),
    )

    first = await service.handle(msg("first", at_bot=False, created_at=100), random_value=0)
    second = await service.handle(msg("second", at_bot=False, created_at=101), random_value=0)

    assert first == "model reply"
    assert second == "model reply"


@pytest.mark.asyncio
async def test_service_ignores_non_whitelisted_group(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("hello", at_bot=True, group=999), random_value=99)

    assert reply is None


@pytest.mark.asyncio
async def test_service_replies_to_private_message_without_group_enable(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(private_msg("你好"), random_value=99)

    assert reply == "model reply"


@pytest.mark.asyncio
async def test_service_does_not_rate_limit_private_messages(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(group_limit=1, user_cooldown_seconds=100),
    )

    first = await service.handle(private_msg("first"), random_value=99)
    second = await service.handle(private_msg("second"), random_value=99)

    assert first == "model reply"
    assert second == "model reply"


@pytest.mark.asyncio
async def test_service_returns_direct_tool_reply(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    tools = FakeToolRunner(direct_reply="Current time: 2026-07-06 09:30:00 (Asia/Shanghai).")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CapturingModel(),
        rate_limiter=RateLimiter(),
        tool_runner=tools,
    )

    reply = await service.handle(private_msg("\u73b0\u5728\u51e0\u70b9"), random_value=99)

    assert reply == "Current time: 2026-07-06 09:30:00 (Asia/Shanghai)."
    assert tools.calls == 1


@pytest.mark.asyncio
async def test_service_passes_tool_context_to_model(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = CapturingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        tool_runner=FakeToolRunner(context="Search query: today news"),
    )

    reply = await service.handle(private_msg("today news"), random_value=99)

    assert reply == "model reply"
    assert "Search query: today news" in model.messages[0]["content"]


@pytest.mark.asyncio
async def test_service_replies_to_addressed_followup_within_window(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(user_cooldown_seconds=0),
        followup_tracker=FollowupTracker(window_seconds=90, trigger_keywords=["你", "怎么看"]),
    )

    first = await service.handle(msg("大哥", at_bot=True, created_at=100), random_value=99)
    second = await service.handle(msg("你怎么看", at_bot=False, created_at=120), random_value=99)

    assert first == "model reply"
    assert second == "model reply"


@pytest.mark.asyncio
async def test_service_ignores_unaddressed_followup_within_window(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(user_cooldown_seconds=0),
        followup_tracker=FollowupTracker(window_seconds=90, trigger_keywords=["你", "怎么看"]),
    )

    first = await service.handle(msg("大哥", at_bot=True, created_at=100), random_value=99)
    second = await service.handle(msg("哈哈哈", at_bot=False, created_at=120), random_value=99)

    assert first == "model reply"
    assert second is None
