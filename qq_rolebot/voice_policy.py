from __future__ import annotations

from qq_rolebot.policy import IncomingMessage


class VoicePolicy:
    def __init__(self, *, trigger_keywords: list[str], cooldown_seconds: int) -> None:
        self.trigger_keywords = [item.lower() for item in trigger_keywords if item.strip()]
        self.cooldown_seconds = cooldown_seconds
        self._last_by_scope: dict[tuple[int, int], int] = {}

    def should_attempt(self, message: IncomingMessage, *, now: int) -> bool:
        if not self.trigger_keywords:
            return False
        if not self._addressed(message):
            return False
        if not self._contains_trigger(message.text):
            return False
        last = self._last_by_scope.get(self._scope(message))
        return last is None or now - last >= self.cooldown_seconds

    def record(self, message: IncomingMessage, *, now: int) -> None:
        self._last_by_scope[self._scope(message)] = now

    def _contains_trigger(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in self.trigger_keywords)

    @staticmethod
    def _addressed(message: IncomingMessage) -> bool:
        return message.is_private or message.is_at_bot or message.is_reply_to_bot

    @staticmethod
    def _scope(message: IncomingMessage) -> tuple[int, int]:
        return (message.group_id, message.user_id)
