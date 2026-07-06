from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolKind, ToolRouter


class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int):
        ...


class PersonaSourceLookup(Protocol):
    async def lookup(self, query: str):
        ...


@dataclass(frozen=True)
class ToolRunResult:
    direct_reply: str | None = None
    context: str = ""


class ToolRunner:
    def __init__(
        self,
        *,
        router: ToolRouter,
        time_tool: TimeTool,
        search_client: SearchClient | None,
        persona_source_client: PersonaSourceLookup | None,
        search_max_results: int,
        enable_time: bool,
        enable_search: bool,
        enable_persona_sources: bool,
    ) -> None:
        self.router = router
        self.time_tool = time_tool
        self.search_client = search_client
        self.persona_source_client = persona_source_client
        self.search_max_results = search_max_results
        self.enable_time = enable_time
        self.enable_search = enable_search
        self.enable_persona_sources = enable_persona_sources

    async def run(self, message: IncomingMessage) -> ToolRunResult:
        plan = self.router.plan(message, now=message.created_at)

        if self.enable_time and ToolKind.TIME in plan.kinds:
            return ToolRunResult(direct_reply=self.time_tool.reply())

        contexts: list[str] = []
        if self.enable_search and ToolKind.SEARCH in plan.kinds and self.search_client is not None:
            search = await self.search_client.search(
                plan.query,
                max_results=self.search_max_results,
            )
            contexts.append(search.format_context())
            self.router.record(message, plan, now=message.created_at)

        if (
            self.enable_persona_sources
            and ToolKind.PERSONA_SOURCE in plan.kinds
            and self.persona_source_client is not None
        ):
            persona_source = await self.persona_source_client.lookup(plan.query)
            contexts.append(persona_source.format_context())

        return ToolRunResult(context="\n\n".join(contexts))
