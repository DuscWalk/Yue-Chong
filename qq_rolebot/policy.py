from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum


class TriggerKind(StrEnum):
    NONE = "none"
    MENTION = "mention"
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
) -> TriggerDecision:
    if not group_enabled:
        return TriggerDecision(False, TriggerKind.NONE, "group disabled")
    if muted_until > now:
        return TriggerDecision(False, TriggerKind.NONE, "group muted")
    if message.is_at_bot:
        return TriggerDecision(True, TriggerKind.MENTION, "mentioned")

    lowered = message.text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return TriggerDecision(True, TriggerKind.KEYWORD, "keyword")

    if random_probability > 0 and random_value < random_probability:
        return TriggerDecision(True, TriggerKind.RANDOM, "random")

    return TriggerDecision(False, TriggerKind.NONE, "no trigger")


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
