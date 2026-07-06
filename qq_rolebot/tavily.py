from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class SearchItem:
    title: str
    url: str
    content: str


@dataclass(frozen=True)
class SearchResponse:
    ok: bool
    query: str
    answer: str = ""
    results: list[SearchItem] | None = None
    error: str = ""

    def format_context(self) -> str:
        if not self.ok:
            return f"Search query: {self.query}\nSearch failed: {self.error}"
        lines = [f"Search query: {self.query}"]
        if self.answer:
            lines.append(f"Answer: {self.answer}")
        for index, item in enumerate(self.results or [], start=1):
            lines.append(f"{index}. {item.title}\nURL: {item.url}\nSnippet: {item.content}")
        if len(lines) == 1:
            lines.append("No current search results were found.")
        return "\n".join(lines)


class TavilyClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def search(self, query: str, *, max_results: int) -> SearchResponse:
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{self.api_base}/search", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return SearchResponse(ok=False, query=query, error=str(exc))

        results = [
            SearchItem(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                content=str(item.get("content", "")),
            )
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]
        return SearchResponse(
            ok=True,
            query=query,
            answer=str(data.get("answer", "") or ""),
            results=results,
        )
