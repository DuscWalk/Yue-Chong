import json
from pathlib import Path

import httpx
import pytest

from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.serpapi_client import (
    SerpApiLensClient,
    SerpApiWebClient,
    canonicalize_url,
    parse_lens_response,
)
from qq_rolebot.vision_types import IdentityCandidate

FIXTURES = Path(__file__).parent / "fixtures" / "serpapi"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_lens_response_normalizes_limits_and_repeated_entities() -> None:
    evidence = parse_lens_response(
        load_fixture("google_lens.json"),
        exact_limit=2,
        visual_limit=3,
    )

    assert len(evidence.exact_matches) == 2
    assert len(evidence.visual_matches) == 3
    assert evidence.exact_matches[0].domain == "arknights.global"
    assert "utm_source" not in evidence.exact_matches[0].url
    assert evidence.repeated_entities == ("重岳", "明日方舟")


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    assert canonicalize_url("https://EXAMPLE.test/a?utm_source=x&id=1#part") == (
        "https://example.test/a?id=1"
    )


@pytest.mark.asyncio
async def test_google_lens_requests_exact_and_visual_matches() -> None:
    requests = []
    fixture = load_fixture("google_lens.json")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        result_type = request.url.params["type"]
        return httpx.Response(200, json={result_type: fixture[result_type]})

    client = SerpApiLensClient(
        api_key="serp-secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("https://public.test/image.png")

    assert result.ok is True
    assert {request.url.params["type"] for request in requests} == {
        "exact_matches",
        "visual_matches",
    }
    assert all(request.url.params["engine"] == "google_lens" for request in requests)
    assert all(request.url.params["url"] == "https://public.test/image.png" for request in requests)
    assert len(result.evidence.exact_matches) == 3
    assert len(result.evidence.visual_matches) == 4


@pytest.mark.asyncio
async def test_google_lens_marks_fetch_error_for_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Google Lens could not fetch image URL"})

    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("https://qq.test/private")

    assert result.ok is False
    assert result.unreachable is True


@pytest.mark.asyncio
async def test_google_web_verification_builds_bounded_query_and_splits_conflicts() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = request.url.params
        return httpx.Response(200, json=load_fixture("google_search.json"))

    client = SerpApiWebClient(
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    candidate = IdentityCandidate(
        name="重岳",
        entity_type="fictional_character",
        work_or_affiliation="明日方舟",
        source_stage="lens_extraction",
    )

    evidence = await client.verify(
        candidate,
        visual_features=("银发", "黑色服装", "不应进入查询"),
    )

    assert captured["params"]["engine"] == "google"
    assert captured["params"]["hl"] == "zh-cn"
    assert "重岳" in captured["params"]["q"]
    assert "银发" in captured["params"]["q"]
    assert "不应进入查询" not in captured["params"]["q"]
    assert len(evidence.supporting_sources) == 2
    assert len(evidence.contradicting_sources) == 1
    assert evidence.contradicting_sources[0].domain == "social.example"


@pytest.mark.asyncio
async def test_serpapi_trace_redacts_api_key_and_image_query(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        result_type = request.url.params["type"]
        return httpx.Response(200, json={result_type: []})

    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)
    trace = logger.start_trace({"text": "识图"})
    client = SerpApiLensClient(
        api_key="serp-secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(handler),
    )

    await client.search("https://signed.test/image?token=private", trace=trace)

    raw = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "serp-secret" not in raw
    assert "token=private" not in raw
    assert "https://signed.test/image" not in raw
    assert "vision.lens.result" in raw
