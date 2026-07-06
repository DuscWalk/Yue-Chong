import httpx
import pytest

from qq_rolebot.persona import PersonaSource
from qq_rolebot.persona_sources import PersonaSourceClient


@pytest.mark.asyncio
async def test_persona_source_fetches_allowlisted_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><h1>Chongyue</h1><p>Archive text.</p></body></html>",
        )

    source = PersonaSource(
        name="PRTS Chongyue",
        url="https://prts.wiki/w/%E9%87%8D%E5%B2%B3",
        purpose="character profile",
    )
    client = PersonaSourceClient(
        sources=[source],
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.lookup("archive")

    assert result.ok is True
    assert "PRTS Chongyue" in result.format_context()
    assert "Archive text." in result.format_context()


@pytest.mark.asyncio
async def test_persona_source_returns_empty_when_no_sources() -> None:
    client = PersonaSourceClient(sources=[], timeout_seconds=5)

    result = await client.lookup("archive")

    assert result.ok is False
    assert result.error == "no persona sources configured"
