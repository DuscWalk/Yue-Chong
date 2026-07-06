from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qq_rolebot.policy import IncomingMessage


class ToolKind(StrEnum):
    TIME = "time"
    SEARCH = "search"
    PERSONA_SOURCE = "persona_source"


@dataclass(frozen=True)
class ToolPlan:
    kinds: tuple[ToolKind, ...]
    query: str
    addressed: bool


SEARCH_KEYWORDS = (
    "search",
    "look up",
    "latest",
    "today",
    "now",
    "news",
    "weather",
    "price",
    "recent",
    "\u67e5\u4e00\u4e0b",
    "\u641c\u4e00\u4e0b",
    "\u5e2e\u6211\u67e5",
    "\u641c\u7d22",
    "\u7f51\u4e0a\u8bf4",
    "\u8d44\u6599",
    "\u5b98\u7f51",
    "\u662f\u771f\u7684\u5417",
    "\u600e\u4e48\u56de\u4e8b",
    "\u4eca\u5929",
    "\u73b0\u5728",
    "\u6700\u65b0",
    "\u65b0\u95fb",
    "\u5929\u6c14",
    "\u4ef7\u683c",
    "\u6700\u8fd1",
    "\u521a\u521a",
    "\u4eca\u5e74",
    "\u672c\u5468",
)

TIME_KEYWORDS = (
    "time",
    "date",
    "\u51e0\u70b9",
    "\u65f6\u95f4",
    "\u51e0\u53f7",
    "\u661f\u671f\u51e0",
)

PERSONA_KEYWORDS = (
    "who are you",
    "background",
    "archive",
    "voice line",
    "lore",
    "nian",
    "dusk",
    "ling",
    "yumen",
    "\u4f60\u662f\u8c01",
    "\u7ecf\u5386",
    "\u6863\u6848",
    "\u8bed\u97f3",
    "\u53f0\u8bcd",
    "\u5e74",
    "\u5915",
    "\u4ee4",
    "\u7389\u95e8",
    "\u8bbe\u5b9a",
)


class ToolRouter:
    def __init__(
        self,
        *,
        search_cooldown_seconds: int,
        persona_names: list[str] | None = None,
    ) -> None:
        self.search_cooldown_seconds = search_cooldown_seconds
        self.persona_names = [name.lower() for name in persona_names or [] if name]
        self._last_search_by_scope: dict[tuple[int, int], int] = {}

    def plan(self, message: IncomingMessage, *, now: int) -> ToolPlan:
        text = message.text.strip()
        lowered = text.lower()
        addressed = message.is_private or message.is_at_bot or message.is_reply_to_bot
        kinds: list[ToolKind] = []

        if addressed and self._contains(lowered, TIME_KEYWORDS):
            kinds.append(ToolKind.TIME)
            return ToolPlan(kinds=tuple(kinds), query=text, addressed=addressed)

        if addressed and self._contains(lowered, SEARCH_KEYWORDS) and self._search_allowed(
            message, now
        ):
            kinds.append(ToolKind.SEARCH)

        role_related = addressed or any(name in lowered for name in self.persona_names)
        if role_related and self._contains(lowered, PERSONA_KEYWORDS):
            kinds.append(ToolKind.PERSONA_SOURCE)

        return ToolPlan(kinds=tuple(kinds), query=text, addressed=addressed)

    def record(self, message: IncomingMessage, plan: ToolPlan, *, now: int) -> None:
        if ToolKind.SEARCH in plan.kinds:
            self._last_search_by_scope[self._scope(message)] = now

    def _search_allowed(self, message: IncomingMessage, now: int) -> bool:
        last = self._last_search_by_scope.get(self._scope(message))
        return last is None or now - last >= self.search_cooldown_seconds

    @staticmethod
    def _scope(message: IncomingMessage) -> tuple[int, int]:
        return (message.group_id, message.user_id)

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)
