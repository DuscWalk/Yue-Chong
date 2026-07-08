import httpx
import pytest

from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.vision_client import VisionClient


def read_trace_events(path):
    files = list(path.glob("*.jsonl"))
    assert len(files) == 1
    return [line for line in files[0].read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_vision_client_sends_image_urls_and_returns_summary() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = request.read()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "一张猫猫表情包，看起来很累。"}}]},
        )

    client = VisionClient(
        api_base="https://vision.example.test/v1",
        api_key="vision-secret",
        model_name="qwen3.6-plus",
        timeout_seconds=5,
        max_images=1,
        enable_search=False,
        transport=httpx.MockTransport(handler),
    )

    result = await client.describe(["https://example.test/a.jpg", "https://example.test/b.jpg"])

    assert result.ok is True
    assert result.summary == "一张猫猫表情包，看起来很累。"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["auth"] == "Bearer vision-secret"
    payload = captured["payload"].decode("utf-8")
    assert '"model":"qwen3.6-plus"' in payload
    assert '"type":"image_url"' in payload
    assert "https://example.test/a.jpg" in payload
    assert "https://example.test/b.jpg" not in payload


@pytest.mark.asyncio
async def test_vision_client_sends_video_and_search_context() -> None:
    captured: dict[str, bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured[request.url.path] = request.read()
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "图里有人举杯，动图里有人挥手。"}}]},
            )
        if request.url.path == "/v1/responses":
            return httpx.Response(200, json={"output_text": "图搜显示可能是某个网络梗图。"})
        return httpx.Response(404)

    client = VisionClient(
        api_base="https://vision.example.test/v1",
        api_key="vision-secret",
        model_name="qwen3.6-plus",
        timeout_seconds=5,
        max_images=1,
        enable_thinking=True,
        enable_search=True,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )

    result = await client.describe(
        ["https://example.test/a.jpg", "https://example.test/b.jpg"],
        video_urls=["https://example.test/wave.gif"],
    )

    assert result.ok is True
    assert result.summary == "图里有人举杯，动图里有人挥手。\n图搜显示可能是某个网络梗图。"
    chat_payload = captured["/v1/chat/completions"].decode("utf-8")
    assert '"enable_thinking":true' in chat_payload
    assert '"type":"image_url"' in chat_payload
    assert '"type":"video_url"' in chat_payload
    assert '"fps":2.0' in chat_payload
    assert "https://example.test/a.jpg" in chat_payload
    assert "https://example.test/b.jpg" not in chat_payload
    assert "https://example.test/wave.gif" in chat_payload

    search_payload = captured["/v1/responses"].decode("utf-8")
    assert '"enable_thinking":true' in search_payload
    assert '"type":"image_search"' in search_payload
    assert '"type":"web_search"' in search_payload
    assert '"type":"input_image"' in search_payload
    assert "https://example.test/a.jpg" in search_payload
    assert "https://example.test/b.jpg" not in search_payload


@pytest.mark.asyncio
async def test_vision_client_writes_full_trace_without_api_key(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "视觉识别：图里是令。"}}]},
            )
        if request.url.path == "/v1/responses":
            return httpx.Response(200, json={"output_text": "搜索结果：未找到可靠来源。"})
        return httpx.Response(404)

    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)
    trace = logger.start_trace({"text": "这是哪个"})
    client = VisionClient(
        api_base="https://vision.example.test/v1",
        api_key="vision-secret",
        model_name="qwen3.6-plus",
        timeout_seconds=5,
        max_images=1,
        enable_search=True,
        transport=httpx.MockTransport(handler),
    )

    result = await client.describe(
        ["https://example.test/private-image.png"],
        video_urls=["https://example.test/move.gif"],
        trace=trace,
    )

    assert result.ok is True
    raw = "\n".join(read_trace_events(tmp_path))
    assert "vision.media.request" in raw
    assert "vision.media.result" in raw
    assert "视觉识别：图里是令。" in raw
    assert "vision.search.request" in raw
    assert "vision.search.result" in raw
    assert "搜索结果：未找到可靠来源。" in raw
    assert "https://example.test/private-image.png" in raw
    assert "https://example.test/move.gif" in raw
    assert "vision-secret" not in raw
    assert "Authorization" not in raw


@pytest.mark.asyncio
async def test_vision_client_skips_empty_image_urls() -> None:
    client = VisionClient(
        api_base="https://vision.example.test/v1",
        api_key="vision-secret",
        model_name="qwen3.6-plus",
        timeout_seconds=5,
        max_images=1,
    )

    result = await client.describe([])

    assert result.ok is False
    assert "no media urls" in result.error
