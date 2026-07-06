from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from qq_rolebot.persona import PersonaSource


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class PersonaSourceResponse:
    ok: bool
    name: str = ""
    url: str = ""
    text: str = ""
    error: str = ""

    def format_context(self) -> str:
        if not self.ok:
            return f"Persona source failed: {self.error}"
        return f"Persona source: {self.name}\nURL: {self.url}\nExcerpt: {self.text}"


class PersonaSourceClient:
    def __init__(
        self,
        *,
        sources: list[PersonaSource],
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
        max_chars: int = 1200,
    ) -> None:
        self.sources = sources
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.max_chars = max_chars
        self._cache: dict[str, PersonaSourceResponse] = {}

    async def lookup(self, query: str) -> PersonaSourceResponse:
        if not self.sources:
            return PersonaSourceResponse(ok=False, error="no persona sources configured")
        source = self.sources[0]
        if source.url in self._cache:
            return self._cache[source.url]
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
                follow_redirects=True,
            ) as client:
                response = await client.get(source.url)
                response.raise_for_status()
        except Exception as exc:
            return PersonaSourceResponse(ok=False, error=str(exc))

        parser = _TextExtractor()
        parser.feed(response.text)
        text = parser.text()[: self.max_chars]
        result = PersonaSourceResponse(ok=True, name=source.name, url=source.url, text=text)
        self._cache[source.url] = result
        return result
