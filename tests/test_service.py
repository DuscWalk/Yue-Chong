from pathlib import Path

import pytest

from qq_rolebot.config import load_settings
from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.model_client import ModelResult
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter
from qq_rolebot.service import ChatService
from qq_rolebot.storage import Storage, VisionContextRecord


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


class QueueModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.messages: list[list[dict[str, str]]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        self.messages.append(messages)
        return ModelResult(ok=True, text=self.replies.pop(0))


class CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        self.calls += 1
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


class FakeVisionClient:
    def __init__(
        self,
        *,
        summary: str = "图片里是一张猫猫表情包。",
        ok: bool = True,
        error: str | None = None,
    ) -> None:
        self.summary = summary
        self.ok = ok
        self.error = error
        self.calls = 0
        self.image_urls: list[str] = []
        self.video_urls: list[str] = []

    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
        trace=None,
    ):
        self.calls += 1
        self.image_urls = image_urls
        self.video_urls = video_urls or []
        if trace is not None:
            trace.event("vision.fake", {"summary": self.summary})

        class Result:
            def __init__(self, *, ok: bool, summary: str, error: str | None) -> None:
                self.ok = ok
                self.summary = summary
                self.error = error

        return Result(ok=self.ok, summary=self.summary, error=self.error)


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
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    media_markers: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        group_id=group,
        user_id=sender,
        nickname="Amy",
        text=text,
        is_at_bot=at_bot,
        created_at=created_at,
        image_urls=image_urls or [],
        video_urls=video_urls or [],
        media_markers=media_markers or [],
    )


def private_msg(
    text: str,
    *,
    sender: int = 99,
    created_at: int = 100,
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    media_markers: list[str] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        group_id=0,
        user_id=sender,
        nickname="Private Amy",
        text=text,
        is_at_bot=False,
        is_private=True,
        created_at=created_at,
        image_urls=image_urls or [],
        video_urls=video_urls or [],
        media_markers=media_markers or [],
    )


def trace_text(path: Path) -> str:
    files = list(path.glob("*.jsonl"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8")


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
async def test_service_follows_repeated_group_message_without_model(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CountingModel()
    tools = FakeToolRunner(context="Search query: repeated")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        tool_runner=tools,
    )

    first = await service.handle(
        msg("好耶", at_bot=False, sender=11, created_at=100),
        random_value=99,
    )
    second = await service.handle(
        msg("好耶", at_bot=False, sender=12, created_at=101),
        random_value=99,
    )

    assert first is None
    assert second == "好耶"
    assert model.calls == 0
    assert tools.calls == 0


@pytest.mark.asyncio
async def test_service_repeat_reply_cools_down_same_message(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CountingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
    )

    first = await service.handle(
        msg("好耶", at_bot=False, sender=11, created_at=100),
        random_value=99,
    )
    second = await service.handle(
        msg("好耶", at_bot=False, sender=12, created_at=101),
        random_value=99,
    )
    blocked = await service.handle(
        msg("好耶", at_bot=False, sender=13, created_at=200),
        random_value=99,
    )
    after_cooldown = await service.handle(
        msg("好耶", at_bot=False, sender=14, created_at=701),
        random_value=99,
    )

    assert first is None
    assert second == "好耶"
    assert blocked is None
    assert after_cooldown == "好耶"
    assert model.calls == 0


@pytest.mark.asyncio
async def test_service_repeat_reply_can_be_disabled(tmp_path: Path) -> None:
    raw_env = env(tmp_path)
    raw_env["REPEAT_REPLY_ENABLED"] = "false"
    settings = load_settings(raw_env)
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CountingModel(),
        rate_limiter=RateLimiter(),
    )

    first = await service.handle(
        msg("好耶", at_bot=False, sender=11, created_at=100),
        random_value=99,
    )
    second = await service.handle(
        msg("好耶", at_bot=False, sender=12, created_at=101),
        random_value=99,
    )

    assert first is None
    assert second is None


@pytest.mark.asyncio
async def test_service_repeat_reply_respects_threshold(tmp_path: Path) -> None:
    raw_env = env(tmp_path)
    raw_env["REPEAT_REPLY_THRESHOLD"] = "3"
    settings = load_settings(raw_env)
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CountingModel(),
        rate_limiter=RateLimiter(),
    )

    first = await service.handle(
        msg("懂了", at_bot=False, sender=11, created_at=100),
        random_value=99,
    )
    second = await service.handle(
        msg("懂了", at_bot=False, sender=12, created_at=101),
        random_value=99,
    )
    third = await service.handle(
        msg("懂了", at_bot=False, sender=13, created_at=102),
        random_value=99,
    )

    assert first is None
    assert second is None
    assert third == "懂了"


@pytest.mark.asyncio
async def test_service_repeat_reply_requires_multiple_users(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CountingModel(),
        rate_limiter=RateLimiter(),
    )

    first = await service.handle(
        msg("好耶", at_bot=False, sender=11, created_at=100),
        random_value=99,
    )
    second = await service.handle(
        msg("好耶", at_bot=False, sender=11, created_at=101),
        random_value=99,
    )

    assert first is None
    assert second is None


@pytest.mark.asyncio
async def test_service_handle_reply_repeats_image_without_model(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CountingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
    )

    first = IncomingMessage(
        group_id=20,
        user_id=11,
        nickname="Amy",
        text="[image: a.jpg]",
        is_at_bot=False,
        created_at=100,
        repeat_media_kind="image",
        repeat_media_file="a.jpg",
        repeat_signature="image:a.jpg",
    )
    second = IncomingMessage(
        group_id=20,
        user_id=12,
        nickname="Bob",
        text="[image: a.jpg]",
        is_at_bot=False,
        created_at=101,
        repeat_media_kind="image",
        repeat_media_file="a.jpg",
        repeat_signature="image:a.jpg",
    )

    assert await service.handle_reply(first, random_value=99) is None
    reply = await service.handle_reply(second, random_value=99)

    assert reply is not None
    assert reply.messages[0].kind == "image"
    assert reply.messages[0].file == "a.jpg"
    assert model.calls == 0


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
async def test_service_saves_bot_replies_in_private_context(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = QueueModel(["上一轮答复", "这一轮答复"])
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
    )

    first = await service.handle(private_msg("第一句", created_at=100), random_value=99)
    second = await service.handle(private_msg("第二句", created_at=101), random_value=99)

    assert first == "上一轮答复"
    assert second == "这一轮答复"
    second_context = model.messages[1][1]["content"]
    assert "Private Amy: 第一句" in second_context
    assert "重岳: 上一轮答复" in second_context


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
async def test_service_appends_sticker_only_after_model_reply(tmp_path: Path) -> None:
    raw_env = env(tmp_path)
    raw_env["MEDIA_REPLY_ENABLED"] = "true"
    raw_env["MEDIA_REPLY_PROBABILITY"] = "100"
    settings = load_settings(raw_env)
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    class FakeEnhancer:
        def enhance(self, reply, *, random_value: int):
            from qq_rolebot.outgoing import OutgoingMessage

            return reply.with_message(
                OutgoingMessage(kind="image", file="calm.webp", source="sticker")
            )

    service.reply_enhancer = FakeEnhancer()

    reply = await service.handle_reply(msg("hello", at_bot=True), random_value=0)

    assert reply is not None
    assert [message.kind for message in reply.messages] == ["text", "image"]


@pytest.mark.asyncio
async def test_service_passes_vision_context_to_model_after_trigger(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CapturingModel()
    vision = FakeVisionClient(summary="图片里是一张猫猫表情包，看起来很累。")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=vision,
    )

    reply = await service.handle(
        msg(
            "[image: https://example.test/cat.jpg]",
            at_bot=True,
            image_urls=["https://example.test/cat.jpg"],
        ),
        random_value=99,
    )

    assert reply == "model reply"
    assert vision.calls == 1
    assert vision.image_urls == ["https://example.test/cat.jpg"]
    assert "Vision Context:" in model.messages[0]["content"]
    assert "图片里是一张猫猫表情包，看起来很累。" in model.messages[0]["content"]


@pytest.mark.asyncio
async def test_service_reuses_latest_image_vision_context_for_visual_followup(
    tmp_path: Path,
) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = QueueModel(["知道了。", "是夕。"])
    vision = FakeVisionClient(summary="纯视觉描述：这是游戏《明日方舟》中的角色“夕”。")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=vision,
    )

    first = await service.handle(
        private_msg(
            "[image: quoted.png]",
            created_at=100,
            image_urls=["https://example.test/quoted.png"],
            media_markers=["[image: quoted.png]"],
        ),
        random_value=99,
    )
    second = await service.handle(private_msg("这谁", created_at=110), random_value=99)

    assert first == "知道了。"
    assert second == "是夕。"
    assert vision.calls == 1
    assert len(model.messages) == 2
    assert "Vision Context:" in model.messages[1][0]["content"]
    assert "这是游戏《明日方舟》中的角色“夕”" in model.messages[1][0]["content"]


@pytest.mark.asyncio
async def test_service_reuses_matching_replied_image_context_without_reidentifying(
    tmp_path: Path,
) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    await storage.save_vision_context(
        VisionContextRecord(
            group_id=20,
            media_marker="[image: quoted.png]",
            summary="纯视觉描述：这是游戏《明日方舟》中的角色“夕”。",
            created_at=100,
        )
    )
    model = CapturingModel()
    vision = FakeVisionClient(summary="不应该调用这条识别。")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=vision,
    )

    reply = await service.handle(
        msg(
            "这谁",
            at_bot=True,
            created_at=120,
            image_urls=["https://example.test/quoted.png"],
            media_markers=["[image: quoted.png]"],
        ),
        random_value=99,
    )

    assert reply == "model reply"
    assert vision.calls == 0
    assert "Vision Context:" in model.messages[0]["content"]
    assert "这是游戏《明日方舟》中的角色“夕”" in model.messages[0]["content"]


@pytest.mark.asyncio
async def test_service_warns_model_not_to_guess_when_vision_fails(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = CapturingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=FakeVisionClient(ok=False, error="timeout"),
    )

    reply = await service.handle(
        private_msg(
            "[image: https://example.test/private-image.png]这是哪个",
            image_urls=["https://example.test/private-image.png"],
        ),
        random_value=99,
    )

    assert reply == "model reply"
    system_prompt = model.messages[0]["content"]
    assert "Vision Context:" in system_prompt
    assert "视觉识别失败" in system_prompt
    assert "不要猜测图片内容" in system_prompt
    assert "timeout" in system_prompt


@pytest.mark.asyncio
async def test_service_traces_private_prompt_model_response_and_reply(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = CapturingModel()
    trace_logger = DebugTraceLogger(root_dir=tmp_path / "traces", now=lambda: 200_000)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=FakeVisionClient(summary="视觉识别：图里是令。"),
        trace_logger=trace_logger,
    )

    reply = await service.handle(
        private_msg(
            "[image: https://example.test/private-image.png]这是哪个",
            image_urls=["https://example.test/private-image.png"],
        ),
        random_value=99,
    )

    assert reply == "model reply"
    raw = trace_text(tmp_path / "traces")
    assert "message.received" in raw
    assert "Private Amy" in raw
    assert "vision.fake" in raw
    assert "视觉识别：图里是令。" in raw
    assert "vision.context" in raw
    assert "model.prompt" in raw
    assert "Vision Context:" in raw
    assert "model.response" in raw
    assert "model reply" in raw
    assert "reply.final" in raw


@pytest.mark.asyncio
async def test_service_passes_video_urls_to_vision_client_after_trigger(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CapturingModel()
    vision = FakeVisionClient(summary="动图里有人挥手。")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        vision_client=vision,
    )

    reply = await service.handle(
        msg(
            "[video: https://example.test/wave.gif]",
            at_bot=True,
            video_urls=["https://example.test/wave.gif"],
        ),
        random_value=99,
    )

    assert reply == "model reply"
    assert vision.calls == 1
    assert vision.image_urls == []
    assert vision.video_urls == ["https://example.test/wave.gif"]
    assert "动图里有人挥手。" in model.messages[0]["content"]


@pytest.mark.asyncio
async def test_service_skips_vision_when_message_does_not_trigger(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    vision = FakeVisionClient()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CapturingModel(),
        rate_limiter=RateLimiter(),
        vision_client=vision,
    )

    reply = await service.handle(
        msg(
            "[image: https://example.test/cat.jpg]",
            at_bot=False,
            image_urls=["https://example.test/cat.jpg"],
        ),
        random_value=99,
    )

    assert reply is None
    assert vision.calls == 0


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
