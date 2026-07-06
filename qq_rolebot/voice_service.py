from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.tts_client import TTSResult
from qq_rolebot.voice_policy import VoicePolicy


class TTSClientProtocol(Protocol):
    async def synthesize(
        self,
        *,
        text: str,
        speaker: str,
        style: str,
        dialect_hint: str,
    ) -> TTSResult:
        ...


@dataclass(frozen=True)
class VoiceRenderResult:
    file_path: Path | None = None
    error: str = ""


class VoiceService:
    def __init__(
        self,
        *,
        enabled: bool,
        policy: VoicePolicy,
        client: TTSClientProtocol,
        cache_dir: Path,
        max_chars: int,
        speaker: str,
        style: str,
        dialect_hint: str,
    ) -> None:
        self.enabled = enabled
        self.policy = policy
        self.client = client
        self.cache_dir = cache_dir
        self.max_chars = max_chars
        self.speaker = speaker
        self.style = style
        self.dialect_hint = dialect_hint

    async def maybe_render(self, message: IncomingMessage, *, reply: str) -> VoiceRenderResult:
        if not self.enabled:
            return VoiceRenderResult()
        if not self.policy.should_attempt(message, now=message.created_at):
            return VoiceRenderResult()

        text = reply.strip()[: self.max_chars]
        if not text:
            return VoiceRenderResult()

        result = await self.client.synthesize(
            text=text,
            speaker=self.speaker,
            style=self.style,
            dialect_hint=self.dialect_hint,
        )
        if not result.ok:
            return VoiceRenderResult(error=result.error)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / self._filename(message, text, result.extension)
        path.write_bytes(result.audio)
        self.policy.record(message, now=message.created_at)
        return VoiceRenderResult(file_path=path)

    @staticmethod
    def _filename(message: IncomingMessage, text: str, extension: str) -> str:
        digest = hashlib.sha256(
            f"{message.group_id}:{message.user_id}:{message.created_at}:{text}".encode()
        ).hexdigest()[:16]
        safe_extension = extension if extension.startswith(".") else f".{extension}"
        return f"{message.created_at}-{message.user_id}-{digest}{safe_extension}"
