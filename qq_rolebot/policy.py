from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import StrEnum


class TriggerKind(StrEnum):
    NONE = "none"
    MENTION = "mention"
    FOLLOWUP = "followup"
    KEYWORD = "keyword"
    RANDOM = "random"


@dataclass(frozen=True)
class IncomingMessage:
    group_id: int
    user_id: int
    nickname: str
    text: str
    is_at_bot: bool
    created_at: int
    is_private: bool = False
    is_reply_to_bot: bool = False
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TriggerDecision:
    should_reply: bool
    kind: TriggerKind
    reason: str


def decide_trigger(
    message: IncomingMessage,
    *,
    group_enabled: bool,
    muted_until: int,
    keywords: list[str],
    random_probability: int,
    now: int,
    random_value: int,
    followup_matched: bool = False,
) -> TriggerDecision:
    if not group_enabled:
        return TriggerDecision(False, TriggerKind.NONE, "group disabled")
    if muted_until > now:
        return TriggerDecision(False, TriggerKind.NONE, "group muted")
    if message.is_at_bot or message.is_reply_to_bot:
        return TriggerDecision(True, TriggerKind.MENTION, "addressed")
    if followup_matched:
        return TriggerDecision(True, TriggerKind.FOLLOWUP, "followup")

    lowered = message.text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return TriggerDecision(True, TriggerKind.KEYWORD, "keyword")

    if random_probability > 0 and random_value < random_probability:
        return TriggerDecision(True, TriggerKind.RANDOM, "random")

    return TriggerDecision(False, TriggerKind.NONE, "no trigger")


class FollowupTracker:
    def __init__(self, *, window_seconds: int, trigger_keywords: list[str]) -> None:
        self.window_seconds = window_seconds
        self.trigger_keywords = [item.lower() for item in trigger_keywords if item.strip()]
        self._active_until: dict[tuple[int, int], int] = {}

    def record(self, message: IncomingMessage, *, now: int) -> None:
        if message.is_private:
            return
        self._active_until[self._scope(message)] = now + self.window_seconds

    def should_trigger(self, message: IncomingMessage, *, now: int) -> bool:
        if message.is_private or message.is_at_bot or message.is_reply_to_bot:
            return False
        active_until = self._active_until.get(self._scope(message), 0)
        if active_until <= now:
            return False
        return self._looks_addressed(message.text)

    def _looks_addressed(self, text: str) -> bool:
        lowered = text.lower()
        if any(mark in lowered for mark in ("?", "？")):
            return True
        return any(keyword in lowered for keyword in self.trigger_keywords)

    @staticmethod
    def _scope(message: IncomingMessage) -> tuple[int, int]:
        return (message.group_id, message.user_id)


class RateLimiter:
    def __init__(
        self,
        *,
        group_limit: int = 3,
        group_window_seconds: int = 60,
        user_cooldown_seconds: int = 10,
    ) -> None:
        self.group_limit = group_limit
        self.group_window_seconds = group_window_seconds
        self.user_cooldown_seconds = user_cooldown_seconds
        self._group_events: dict[int, deque[int]] = defaultdict(deque)
        self._user_events: dict[tuple[int, int], int] = {}

    def allow(self, group_id: int, user_id: int, *, now: int) -> bool:
        self._prune(group_id, now)
        user_key = (group_id, user_id)
        last_user_reply = self._user_events.get(user_key)
        if last_user_reply is not None and now - last_user_reply < self.user_cooldown_seconds:
            return False
        return len(self._group_events[group_id]) < self.group_limit

    def record(self, group_id: int, user_id: int, *, now: int) -> None:
        self._prune(group_id, now)
        self._group_events[group_id].append(now)
        self._user_events[(group_id, user_id)] = now

    def _prune(self, group_id: int, now: int) -> None:
        events = self._group_events[group_id]
        while events and now - events[0] >= self.group_window_seconds:
            events.popleft()
