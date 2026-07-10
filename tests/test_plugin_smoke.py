import asyncio
import importlib
from types import SimpleNamespace


def set_env(monkeypatch) -> None:
    values = {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": "data/test.sqlite3",
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
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_bot_entrypoint_imports(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("bot")
    assert hasattr(module, "main")


def test_roleplay_plugin_imports(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    assert hasattr(module, "extract_message_text")


def test_plugin_builds_private_incoming_message(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="private",
        user_id=99,
        sender=SimpleNamespace(nickname="Amy"),
        time=123,
        get_plaintext=lambda: "你好",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.group_id == 0
    assert incoming.user_id == 99
    assert incoming.nickname == "Amy"
    assert incoming.text == "你好"
    assert incoming.is_private is True


def test_plugin_marks_reply_to_bot(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        message=[
            SimpleNamespace(type="reply", data={"id": "123"}),
            SimpleNamespace(type="text", data={"text": "today news"}),
        ],
        reply=SimpleNamespace(sender=SimpleNamespace(user_id=10001)),
        get_plaintext=lambda: "today news",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.is_reply_to_bot is True
    assert incoming.text == "today news"


def test_plugin_uses_nonebot_to_me_after_at_segment_removed(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="text", data={"text": "hello"}),
        ],
        get_plaintext=lambda: "hello",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.is_at_bot is True


def test_plugin_extracts_image_urls_into_incoming_message(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="text", data={"text": "看看这个"}),
            SimpleNamespace(type="image", data={"url": "https://example.test/meme.jpg"}),
        ],
        get_plaintext=lambda: "看看这个",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.text == "看看这个 [image: https://example.test/meme.jpg]"
    assert incoming.image_urls == ["https://example.test/meme.jpg"]
    assert incoming.video_urls == []


def test_plugin_extracts_dynamic_media_into_incoming_message(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="text", data={"text": "看看这个"}),
            SimpleNamespace(type="image", data={"url": "https://example.test/meme.gif"}),
            SimpleNamespace(type="video", data={"url": "https://example.test/clip.mp4"}),
        ],
        get_plaintext=lambda: "看看这个",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.text == (
        "看看这个 [image: https://example.test/meme.gif] "
        "[video: https://example.test/clip.mp4]"
    )
    assert incoming.image_urls == []
    assert incoming.video_urls == [
        "https://example.test/meme.gif",
        "https://example.test/clip.mp4",
    ]


def test_plugin_uses_replied_message_image_urls(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="reply", data={"id": "12345"}),
            SimpleNamespace(type="text", data={"text": "这是谁"}),
        ],
        reply=SimpleNamespace(
            sender=SimpleNamespace(user_id=42),
            message=[
                SimpleNamespace(type="image", data={"url": "https://example.test/quoted.jpg"})
            ],
        ),
        get_plaintext=lambda: "这是谁",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.text == "这是谁"
    assert incoming.image_urls == ["https://example.test/quoted.jpg"]
    assert incoming.media_source == "replied_message"
    assert incoming.reply_message_id == "12345"


async def test_handle_message_fetches_replied_image_when_reply_payload_missing(
    monkeypatch,
) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    seen = {}

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            seen["incoming"] = incoming
            return None

    class FakeBot:
        async def get_msg(self, *, message_id):
            seen["message_id"] = message_id
            return {
                "message": [
                    {
                        "type": "image",
                        "data": {"url": "https://example.test/fetched.jpg"},
                    }
                ]
            }

        async def send(self, event, message):
            raise AssertionError("should not send")

    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="reply", data={"id": "12345"}),
            SimpleNamespace(type="text", data={"text": "这是谁"}),
        ],
        reply=SimpleNamespace(sender=SimpleNamespace(user_id=42), message=[]),
        get_plaintext=lambda: "这是谁",
    )
    monkeypatch.setattr(module, "service", FakeService())

    await module.handle_message(FakeBot(), event)

    assert seen["message_id"] == 12345
    assert seen["incoming"].image_urls == ["https://example.test/fetched.jpg"]
    assert seen["incoming"].media_source == "replied_message_fetch"
    assert seen["incoming"].reply_message_id == "12345"


async def test_handle_message_continues_when_replied_message_fetch_fails(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    seen = {}

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            seen["incoming"] = incoming
            return None

    class FakeBot:
        async def get_msg(self, *, message_id):
            raise RuntimeError("message expired")

        async def send(self, event, message):
            raise AssertionError("should not send")

    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=True,
        message=[
            SimpleNamespace(type="reply", data={"id": "12345"}),
            SimpleNamespace(type="text", data={"text": "这是谁"}),
        ],
        reply=SimpleNamespace(sender=SimpleNamespace(user_id=42), message=[]),
        get_plaintext=lambda: "这是谁",
    )
    monkeypatch.setattr(module, "service", FakeService())

    await module.handle_message(FakeBot(), event)

    assert seen["incoming"].image_urls == []
    assert seen["incoming"].reply_message_id == "12345"


async def test_handle_message_serializes_same_private_chat(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    calls = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            calls.append(f"start:{incoming.text}")
            if incoming.text == "first":
                first_started.set()
                await release_first.wait()
            calls.append(f"end:{incoming.text}")
            return None

    class FakeBot:
        async def send(self, event, message):
            raise AssertionError("should not send")

    def event(text: str):
        return SimpleNamespace(
            message_type="private",
            user_id=99,
            sender=SimpleNamespace(nickname="Amy"),
            time=123,
            message=[SimpleNamespace(type="text", data={"text": text})],
            get_plaintext=lambda: text,
        )

    monkeypatch.setattr(module, "service", FakeService())

    first = asyncio.create_task(module.handle_message(FakeBot(), event("first")))
    await first_started.wait()
    second = asyncio.create_task(module.handle_message(FakeBot(), event("second")))
    await asyncio.sleep(0.01)

    assert calls == ["start:first"]

    release_first.set()
    await asyncio.gather(first, second)

    assert calls == ["start:first", "end:first", "start:second", "end:second"]


async def test_handle_message_serializes_same_group_chat(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    calls = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            calls.append(f"start:{incoming.user_id}:{incoming.text}")
            if incoming.text == "first":
                first_started.set()
                await release_first.wait()
            calls.append(f"end:{incoming.user_id}:{incoming.text}")
            return None

    class FakeBot:
        async def send(self, event, message):
            raise AssertionError("should not send")

    def event(text: str, user_id: int):
        return SimpleNamespace(
            message_type="group",
            group_id=20,
            user_id=user_id,
            sender=SimpleNamespace(nickname="Amy", card=""),
            time=123,
            to_me=True,
            message=[SimpleNamespace(type="text", data={"text": text})],
            get_plaintext=lambda: text,
        )

    monkeypatch.setattr(module, "service", FakeService())

    first = asyncio.create_task(module.handle_message(FakeBot(), event("first", 99)))
    await first_started.wait()
    second = asyncio.create_task(module.handle_message(FakeBot(), event("second", 100)))
    await asyncio.sleep(0.01)

    assert calls == ["start:99:first"]

    release_first.set()
    await asyncio.gather(first, second)

    assert calls == [
        "start:99:first",
        "end:99:first",
        "start:100:second",
        "end:100:second",
    ]


async def test_handle_message_allows_different_private_chats_in_parallel(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    calls = []
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            calls.append(f"start:{incoming.user_id}:{incoming.text}")
            if incoming.text == "first":
                first_started.set()
                await release_first.wait()
            if incoming.text == "second":
                second_started.set()
            calls.append(f"end:{incoming.user_id}:{incoming.text}")
            return None

    class FakeBot:
        async def send(self, event, message):
            raise AssertionError("should not send")

    def event(text: str, user_id: int):
        return SimpleNamespace(
            message_type="private",
            user_id=user_id,
            sender=SimpleNamespace(nickname="Amy"),
            time=123,
            message=[SimpleNamespace(type="text", data={"text": text})],
            get_plaintext=lambda: text,
        )

    monkeypatch.setattr(module, "service", FakeService())

    first = asyncio.create_task(module.handle_message(FakeBot(), event("first", 99)))
    await first_started.wait()
    second = asyncio.create_task(module.handle_message(FakeBot(), event("second", 100)))
    await asyncio.wait_for(second_started.wait(), timeout=1)

    assert calls == ["start:99:first", "start:100:second", "end:100:second"]

    release_first.set()
    await asyncio.gather(first, second)

    assert calls == [
        "start:99:first",
        "start:100:second",
        "end:100:second",
        "end:99:first",
    ]


def test_plugin_does_not_mark_reply_to_other_user_as_reply_to_bot(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=False,
        message=[
            SimpleNamespace(type="reply", data={"id": "123"}),
            SimpleNamespace(type="text", data={"text": "not for bot"}),
        ],
        reply=SimpleNamespace(sender=SimpleNamespace(user_id=12345)),
        get_plaintext=lambda: "not for bot",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.is_reply_to_bot is False


def test_plugin_extracts_repeat_face_metadata(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=False,
        message=[SimpleNamespace(type="face", data={"id": "14"})],
        get_plaintext=lambda: "",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming is not None
    assert incoming.repeat_media_kind == "face"
    assert incoming.repeat_media_face_id == "14"
    assert incoming.repeat_signature == "face:14"


def test_roleplay_plugin_builds_tool_runner(monkeypatch) -> None:
    set_env(monkeypatch)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    assert module.service.tool_runner is not None


def test_roleplay_plugin_builds_voice_service_when_enabled(monkeypatch) -> None:
    set_env(monkeypatch)
    monkeypatch.setenv("TTS_ENABLED", "true")
    monkeypatch.setenv("TTS_API_URL", "http://127.0.0.1:5005")
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    assert module.voice_service is not None


async def test_handle_message_sends_voice_record_when_rendered(monkeypatch, tmp_path) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    audio_path = tmp_path / "reply.wav"
    audio_path.write_bytes(b"audio")

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            return "一切安好。"

    class FakeVoiceService:
        async def maybe_render(self, incoming, *, reply: str):
            return SimpleNamespace(file_path=audio_path)

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message):
            self.sent.append(message)

    event = SimpleNamespace(
        message_type="private",
        user_id=99,
        sender=SimpleNamespace(nickname="Amy"),
        time=123,
        message=[],
        get_plaintext=lambda: "用语音说一句",
    )
    bot = FakeBot()
    monkeypatch.setattr(module, "service", FakeService())
    monkeypatch.setattr(module, "voice_service", FakeVoiceService())

    await module.handle_message(bot, event)

    assert bot.sent
    assert "record" in str(bot.sent[0])


async def test_handle_message_sends_text_when_voice_not_rendered(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    class FakeService:
        async def handle(self, incoming, *, random_value: int):
            return "一切安好。"

    class FakeVoiceService:
        async def maybe_render(self, incoming, *, reply: str):
            return SimpleNamespace(file_path=None)

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message):
            self.sent.append(message)

    event = SimpleNamespace(
        message_type="private",
        user_id=99,
        sender=SimpleNamespace(nickname="Amy"),
        time=123,
        message=[],
        get_plaintext=lambda: "你好",
    )
    bot = FakeBot()
    monkeypatch.setattr(module, "service", FakeService())
    monkeypatch.setattr(module, "voice_service", FakeVoiceService())

    await module.handle_message(bot, event)

    assert bot.sent
    assert "record" not in str(bot.sent[0])
    assert "一切安好" in str(bot.sent[0])


async def test_render_outgoing_reply_sends_text_and_image_separately(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message):
            self.sent.append(str(message))

    bot = FakeBot()
    reply = OutgoingReply(
        source="model",
        messages=[
            OutgoingMessage(kind="text", text="一切安好。"),
            OutgoingMessage(kind="image", file="/opt/qq-rolebot/stickers/calm.webp"),
        ],
    )

    await module.send_outgoing_reply(bot, object(), reply)

    assert len(bot.sent) == 2
    assert "一切安好" in bot.sent[0]
    assert "image" in bot.sent[1]
