from dataclasses import dataclass

import pytest

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.tts_client import TTSResult
from qq_rolebot.voice_policy import VoicePolicy
from qq_rolebot.voice_service import VoiceService


def msg(text: str, *, private: bool = True) -> IncomingMessage:
    return IncomingMessage(
        group_id=0 if private else 20001,
        user_id=10001,
        nickname="Amy",
        text=text,
        is_at_bot=not private,
        is_private=private,
        created_at=100,
    )


@dataclass
class FakeTTSClient:
    result: TTSResult
    calls: list[str]

    async def synthesize(self, *, text: str, speaker: str, style: str, dialect_hint: str):
        self.calls.append(text)
        return self.result


@pytest.mark.asyncio
async def test_voice_service_skips_when_policy_rejects(tmp_path) -> None:
    client = FakeTTSClient(result=TTSResult(ok=True, audio=b"audio"), calls=[])
    service = VoiceService(
        enabled=True,
        policy=VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120),
        client=client,
        cache_dir=tmp_path,
        max_chars=80,
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )

    result = await service.maybe_render(msg("你好"), reply="一切安好。")

    assert result.file_path is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_voice_service_writes_audio_file_and_records_cooldown(tmp_path) -> None:
    client = FakeTTSClient(result=TTSResult(ok=True, audio=b"audio", extension=".wav"), calls=[])
    policy = VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120)
    service = VoiceService(
        enabled=True,
        policy=policy,
        client=client,
        cache_dir=tmp_path,
        max_chars=4,
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )
    message = msg("用语音说")

    result = await service.maybe_render(message, reply="一二三四五六")

    assert result.file_path is not None
    assert result.file_path.read_bytes() == b"audio"
    assert result.file_path.suffix == ".wav"
    assert client.calls == ["一二三四"]
    assert policy.should_attempt(message, now=150) is False


@pytest.mark.asyncio
async def test_voice_service_returns_empty_result_on_client_failure(tmp_path) -> None:
    client = FakeTTSClient(result=TTSResult(ok=False, error="busy"), calls=[])
    service = VoiceService(
        enabled=True,
        policy=VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120),
        client=client,
        cache_dir=tmp_path,
        max_chars=80,
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )

    result = await service.maybe_render(msg("语音说一句"), reply="一切安好。")

    assert result.file_path is None
    assert result.error == "busy"
