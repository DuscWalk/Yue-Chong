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
        get_plaintext=lambda: "today news",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.is_reply_to_bot is True
    assert incoming.text == "today news"


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
