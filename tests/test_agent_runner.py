from pathlib import Path

import pytest

from qq_rolebot.agent_runner import AgentRunner
from qq_rolebot.config import load_settings
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.storage import MessageRecord


class FakeModel:
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        assert messages
        return ModelResult(ok=True, text=" model reply ")


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
    }


@pytest.mark.asyncio
async def test_agent_runner_returns_clean_text(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    runner = AgentRunner(settings=settings, model=FakeModel())
    message = IncomingMessage(
        group_id=20,
        user_id=11,
        nickname="Amy",
        text="hello",
        is_at_bot=True,
        created_at=100,
    )

    result = await runner.run(
        persona=load_persona(settings.persona_path),
        context=[MessageRecord(20, 11, "Amy", "hello", 100)],
        message=message,
        tool_context="",
    )

    assert result.ok is True
    assert result.text == "model reply"
