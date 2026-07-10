from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from qq_rolebot.config import Settings
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import Persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.storage import MessageRecord


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        ...


@dataclass(frozen=True)
class AgentRunResult:
    ok: bool
    text: str = ""
    error: str = ""
    messages: list[dict[str, str]] | None = None
    model_text: str = ""
    elapsed_ms: int = 0


class AgentRunner:
    def __init__(self, *, settings: Settings, model: ChatModel) -> None:
        self.settings = settings
        self.model = model

    async def run(
        self,
        *,
        persona: Persona,
        context: list[MessageRecord],
        message: IncomingMessage,
        tool_context: str,
    ) -> AgentRunResult:
        messages = build_chat_messages(persona, context, message, tool_context=tool_context)
        started = time.monotonic()
        result = await self.model.chat(messages)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if not result.ok:
            return AgentRunResult(
                ok=False,
                error=result.error,
                messages=messages,
                model_text=result.text,
                elapsed_ms=elapsed_ms,
            )
        text = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if text is None:
            return AgentRunResult(
                ok=False,
                error="guardrails rejected response",
                messages=messages,
                model_text=result.text,
                elapsed_ms=elapsed_ms,
            )
        return AgentRunResult(
            ok=True,
            text=text,
            messages=messages,
            model_text=result.text,
            elapsed_ms=elapsed_ms,
        )
