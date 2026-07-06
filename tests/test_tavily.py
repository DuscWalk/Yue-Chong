import httpx
import pytest

from qq_rolebot.tavily import TavilyClient


@pytest.mark.asyncio
async def test_tavily_client_formats_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        payload = {
            "answer": "Short answer",
            "results": [
                {
                    "title": "Result One",
                    "url": "https://example.test/one",
                    "content": "Useful snippet.",
                }
            ],
        }
        return httpx.Response(200, json=payload)

    client = TavilyClient(
        api_key="key",
        api_base="https://api.tavily.com",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("query", max_results=3)

    assert result.ok is True
    assert result.answer == "Short answer"
    assert result.results[0].title == "Result One"
    assert result.format_context().startswith("Search query: query")


@pytest.mark.asyncio
async def test_tavily_client_handles_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "bad"})

    client = TavilyClient(
        api_key="key",
        api_base="https://api.tavily.com",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("query", max_results=3)

    assert result.ok is False
    assert result.error
