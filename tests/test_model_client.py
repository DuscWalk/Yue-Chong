import httpx
import pytest

from qq_rolebot.model_client import ModelClient


@pytest.mark.asyncio
async def test_model_client_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello from model"}}]},
        )

    client = ModelClient(
        api_base="https://example.test/v1",
        api_key="secret",
        model_name="chat-model",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat([{"role": "user", "content": "hello"}])

    assert result.ok is True
    assert result.text == "hello from model"


@pytest.mark.asyncio
async def test_model_client_returns_failure_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "failed"})

    client = ModelClient(
        api_base="https://example.test/v1",
        api_key="secret",
        model_name="chat-model",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat([{"role": "user", "content": "hello"}])

    assert result.ok is False
    assert "500" in result.error
