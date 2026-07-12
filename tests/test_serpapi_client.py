import json
from pathlib import Path
from urllib.parse import parse_qs

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


@pytest.mark.asyncio
async def test_lens_all_submits_async_and_polls_until_success() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/search.json":
            return httpx.Response(200, json=load_fixture("google_lens_all_processing.json"))
        assert request.url.path == "/searches/synthetic-search-id.json"
        return httpx.Response(200, json=load_fixture("google_lens_all_success.json"))

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = SerpApiLensClient(
        api_key="serp-secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        poll_interval_seconds=0.75,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
    )

    result = await client.search_all("https://public.test/image.png?token=private")
    await client.close()

    submit = requests[0]
    assert submit.url.params["engine"] == "google_lens"
    assert submit.url.params["type"] == "all"
    assert submit.url.params["async"] == "true"
    assert submit.url.params["auto_crop"] == "false"
    assert "no_cache" not in submit.url.params
    assert len(requests) == 2
    assert sleeps == [0.75]
    assert result.ok is True
    assert result.cached is False
    assert len(result.evidence.visual_matches) == 2
    assert len(result.evidence.related_content) == 1
    assert result.evidence.ai_overview == "Synthetic overview text for a fictional image."


@pytest.mark.asyncio
async def test_lens_all_cached_success_does_not_poll_or_call_exact() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = load_fixture("google_lens_all_success.json")
        payload["search_metadata"]["status"] = "Cached"
        return httpx.Response(200, json=payload)

    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search_all("https://public.test/cached.png")
    await client.close()

    assert result.ok is True
    assert result.cached is True
    assert len(requests) == 1
    assert requests[0].url.params["type"] == "all"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"search_metadata": {"status": "Error"}, "error": "synthetic failure"},
        {"search_metadata": {"status": "Processing"}},
    ],
)
async def test_lens_all_returns_failure_for_error_or_missing_search_id(response: dict) -> None:
    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)),
    )

    result = await client.search_all("https://public.test/failure.png")
    await client.close()

    assert result.ok is False
    assert result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,content", [(200, b"not-json"), (503, b"unavailable")])
async def test_lens_all_returns_failure_for_malformed_or_http_response(
    status_code: int,
    content: bytes,
) -> None:
    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, content=content)
        ),
    )

    result = await client.search_all("https://public.test/failure.png")
    await client.close()

    assert result.ok is False
    assert "secret" not in result.error
    assert "https://public.test/failure.png" not in result.error


@pytest.mark.asyncio
async def test_lens_all_sanitizes_provider_error_text() -> None:
    client = SerpApiLensClient(
        api_key="serp-secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "search_metadata": {"status": "Error"},
                    "error": (
                        "could not fetch https://signed.test/image?token=private "
                        "with serp-secret"
                    ),
                },
            )
        ),
    )

    result = await client.search_all("https://signed.test/image?token=private")
    await client.close()

    assert result.ok is False
    assert result.unreachable is True
    assert "serp-secret" not in result.error
    assert "token=private" not in result.error
    assert "https://signed.test/image" not in result.error


@pytest.mark.asyncio
async def test_lens_all_stops_polling_at_absolute_deadline() -> None:
    now = 10.0

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay

    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=1.5,
        exact_limit=5,
        visual_limit=10,
        poll_interval_seconds=0.75,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=load_fixture("google_lens_all_processing.json")
            )
        ),
        sleep=sleep,
        clock=clock,
    )

    result = await client.search_all("https://public.test/slow.png")
    await client.close()

    assert result.ok is False
    assert "deadline" in result.error.casefold()


@pytest.mark.asyncio
async def test_exact_search_is_conditional_and_does_not_discard_prior_all_result() -> None:
    request_types: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_type = request.url.params.get("type", "poll")
        request_types.append(request_type)
        if request_type == "all":
            return httpx.Response(200, json=load_fixture("google_lens_all_success.json"))
        return httpx.Response(
            200,
            json={"search_metadata": {"status": "Error"}, "error": "exact unavailable"},
        )

    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(handler),
    )

    all_result = await client.search_all("https://public.test/image.png")
    exact_result = await client.search_exact("https://public.test/image.png", timeout_seconds=2)
    await client.close()

    assert all_result.ok is True
    assert len(all_result.evidence.visual_matches) == 2
    assert exact_result.ok is False
    assert request_types == ["all", "exact_matches"]


@pytest.mark.asyncio
async def test_exact_search_parses_sources() -> None:
    client = SerpApiLensClient(
        api_key="secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=load_fixture("google_lens_exact_success.json")
            )
        ),
    )

    result = await client.search_exact("https://public.test/image.png")
    await client.close()

    assert result.ok is True
    assert len(result.sources) == 1
    assert result.sources[0].domain == "exact.example"
    assert "ref=" not in result.sources[0].url


@pytest.mark.asyncio
async def test_google_web_search_bounds_query_and_returns_normalized_sources() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(parse_qs(request.url.query.decode()))
        return httpx.Response(200, json=load_fixture("google_search.json"))

    client = SerpApiWebClient(
        api_key="secret",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    sources = await client.search("识别角色 " + "很长" * 200)
    await client.close()

    assert captured["engine"] == ["google"]
    assert captured["hl"] == ["zh-cn"]
    assert len(captured["q"][0]) == 250
    assert len(sources) == 3
    assert sources[0].result_kind == "web"


@pytest.mark.asyncio
async def test_lens_all_trace_never_contains_key_search_id_or_complete_image_url(tmp_path) -> None:
    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)
    trace = logger.start_trace({"text": "识图"})
    responses = iter(
        [
            load_fixture("google_lens_all_processing.json"),
            load_fixture("google_lens_all_success.json"),
        ]
    )
    client = SerpApiLensClient(
        api_key="serp-secret",
        timeout_seconds=5,
        exact_limit=5,
        visual_limit=10,
        poll_interval_seconds=0.01,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=next(responses))
        ),
        sleep=lambda delay: _no_sleep(),
    )

    await client.search_all(
        "https://signed.test/private/image?token=private",
        trace=trace,
    )
    await client.close()

    raw = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "serp-secret" not in raw
    assert "synthetic-search-id" not in raw
    assert "token=private" not in raw
    assert "https://signed.test/private/image" not in raw
    assert "vision.lens_all.submit" in raw
    assert "vision.lens_all.result" in raw


async def _no_sleep() -> None:
    return None
