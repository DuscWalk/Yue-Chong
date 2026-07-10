from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

from qq_rolebot.image_preprocessor import NormalizedImage
from qq_rolebot.serpapi_client import LensSearchResult
from qq_rolebot.vision_client import VisualAnalysis
from qq_rolebot.vision_pipeline import VisionPipeline
from qq_rolebot.vision_resolver import ResolverDecision
from qq_rolebot.vision_types import (
    CandidateWebEvidence,
    ConfidenceBand,
    IdentityCandidate,
    LensEvidence,
    SearchSource,
    VisionObservation,
    VisionResolution,
)


def normalized(url: str) -> NormalizedImage:
    value = url.rsplit("/", 1)[-1]
    return NormalizedImage(
        content=b"image",
        content_type="image/png",
        width=10,
        height=10,
        sha256=(value + "0" * 64)[:64],
        source_url=url,
    )


class FakePreprocessor:
    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.urls: list[str] = []

    async def fetch(self, url, *, trace=None, timeout_seconds=None):
        self.urls.append(url)
        await asyncio.sleep(self.delay)
        return normalized(url)


class PerUrlPreprocessor(FakePreprocessor):
    def __init__(self, delays: dict[str, float]) -> None:
        super().__init__()
        self.delays = delays

    async def fetch(self, url, *, trace=None, timeout_seconds=None):
        self.urls.append(url)
        await asyncio.sleep(self.delays.get(url, 0))
        return normalized(url)


class FakeAnalyzer:
    def __init__(self, delay: float = 0, *, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.image_calls = 0
        self.dynamic_calls = 0

    async def analyze_image(
        self,
        image,
        *,
        user_question,
        chat_context,
        trace=None,
        timeout_seconds=None,
    ):
        self.image_calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            return VisualAnalysis(VisionObservation(), error="failed")
        return VisualAnalysis(
            observation=VisionObservation(
                scene_description="一名银发动画角色。",
                distinctive_features=("银发", "黑色服装"),
            ),
            candidates=(
                IdentityCandidate(
                    name="重岳",
                    entity_type="fictional_character",
                    work_or_affiliation="明日方舟",
                    source_stage="visual",
                ),
            ),
        )

    async def extract_search_candidates(
        self,
        lens,
        *,
        observation,
        user_question,
        trace=None,
        timeout_seconds=None,
    ):
        return (
            IdentityCandidate(
                name="重岳",
                entity_type="fictional_character",
                work_or_affiliation="明日方舟",
                source_stage="lens_extraction",
            ),
        )

    async def describe_dynamic_media(
        self,
        video_urls,
        *,
        user_question,
        trace=None,
        timeout_seconds=None,
    ):
        self.dynamic_calls += 1
        return VisionObservation(scene_description="有人挥手。")


class FakeLens:
    def __init__(self, results: list[LensSearchResult], delay: float = 0) -> None:
        self.results = results
        self.delay = delay
        self.urls: list[str] = []

    async def search(self, url, *, trace=None, timeout_seconds=None):
        self.urls.append(url)
        await asyncio.sleep(self.delay)
        return self.results[min(len(self.urls) - 1, len(self.results) - 1)]


class FakeWeb:
    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.calls: list[str] = []

    async def verify(self, candidate, *, visual_features, trace=None, timeout_seconds=None):
        self.calls.append(candidate.name)
        await asyncio.sleep(self.delay)
        return CandidateWebEvidence(
            candidate_name=candidate.name,
            supporting_sources=(
                SearchSource(
                    title="重岳 明日方舟",
                    url="https://wiki.test/a",
                    domain="wiki.test",
                    result_kind="web",
                ),
            ),
        )


@dataclass
class FakeHandle:
    url: str = "https://signed.test/fallback"
    object_key: str = "temp/key"
    deleted: int = 0

    async def delete(self):
        self.deleted += 1


class FakeStore:
    def __init__(self, delay: float = 0) -> None:
        self.delay = delay
        self.calls = 0
        self.handles: list[FakeHandle] = []

    async def publish(self, image, *, trace=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        handle = FakeHandle()
        self.handles.append(handle)
        return handle


class FakeCache:
    def __init__(
        self,
        cached: VisionResolution | None = None,
        *,
        cached_observation: VisionObservation | None = None,
        cached_lens: LensEvidence | None = None,
    ) -> None:
        self.cached = cached
        self.cached_observation = cached_observation
        self.cached_lens = cached_lens
        self.put_resolutions = 0
        self.put_observations = 0
        self.put_lens_results = 0

    async def get_resolution(self, image_hash, *, version, now):
        return self.cached

    async def put_resolution(self, image_hash, *, version, resolution, now):
        self.cached = resolution
        self.put_resolutions += 1

    async def get_observation(self, image_hash, *, version, now):
        return self.cached_observation

    async def put_observation(self, image_hash, *, version, observation, now):
        self.cached_observation = observation
        self.put_observations += 1

    async def get_lens(self, image_hash, *, version, now):
        return self.cached_lens

    async def put_lens(self, image_hash, *, version, lens, now):
        self.cached_lens = lens
        self.put_lens_results += 1


class ConfirmingResolver:
    def select_web_candidates(self, visual_candidates, lens, *, limit):
        seen = {}
        for item in visual_candidates:
            seen.setdefault(item.name, item)
        return tuple(seen.values())[:limit]

    def resolve(self, *, observation, visual_candidates, lens, web_evidence):
        identity = visual_candidates[0]
        return ResolverDecision(
            resolution=VisionResolution.confirmed(
                observation=observation,
                identity_name=identity.name,
                work_or_affiliation=identity.work_or_affiliation,
                evidence_summary="独立证据一致。",
            ),
            rule_id="test_confirm",
        )


def lens_success() -> LensSearchResult:
    return LensSearchResult(
        ok=True,
        evidence=LensEvidence(
            exact_matches=(
                SearchSource(
                    title="重岳 明日方舟",
                    url="https://official.test/a",
                    domain="official.test",
                    result_kind="exact",
                ),
            ),
        ),
    )


def make_pipeline(*, analyzer=None, lens=None, store=None, cache=None, timeout=1.0, max_images=2):
    return VisionPipeline(
        preprocessor=FakePreprocessor(),
        analyzer=analyzer or FakeAnalyzer(),
        lens_client=lens or FakeLens([lens_success()]),
        web_client=FakeWeb(),
        temp_store=store or FakeStore(),
        resolver=ConfirmingResolver(),
        cache=cache or FakeCache(),
        total_timeout_seconds=timeout,
        max_images=max_images,
        web_candidate_limit=2,
        cache_version="test-v1",
        now=lambda: 100,
    )


@pytest.mark.asyncio
async def test_pipeline_runs_visual_and_publication_concurrently() -> None:
    analyzer = FakeAnalyzer(delay=0.08)
    store = FakeStore(delay=0.08)
    pipeline = make_pipeline(analyzer=analyzer, store=store)

    started = time.monotonic()
    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="最近在聊明日方舟。",
    )
    elapsed = time.monotonic() - started
    await pipeline.close()

    assert elapsed < 0.15
    assert result.resolutions[0].confidence is ConfidenceBand.CONFIRMED
    assert store.handles[0].deleted == 1


@pytest.mark.asyncio
async def test_pipeline_uses_r2_only_after_original_lens_fetch_failure() -> None:
    lens = FakeLens(
        [
            LensSearchResult(ok=False, unreachable=True, error="could not fetch"),
            lens_success(),
        ]
    )
    pipeline = make_pipeline(lens=lens)

    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert result.ok is True
    assert lens.urls == ["https://qq.test/a.png", "https://signed.test/fallback"]


@pytest.mark.asyncio
async def test_pipeline_does_not_repeat_lens_after_original_success() -> None:
    lens = FakeLens([lens_success()])
    pipeline = make_pipeline(lens=lens)

    await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert lens.urls == ["https://qq.test/a.png"]


@pytest.mark.asyncio
async def test_pipeline_original_lens_success_does_not_wait_for_slow_r2() -> None:
    store = FakeStore(delay=0.3)
    pipeline = make_pipeline(store=store, timeout=1)

    started = time.monotonic()
    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    elapsed = time.monotonic() - started

    assert result.ok is True
    assert elapsed < 0.15
    await pipeline.close()
    assert store.handles[0].deleted == 1


@pytest.mark.asyncio
async def test_pipeline_complete_cache_hit_skips_providers() -> None:
    cached = VisionResolution.confirmed(
        observation=VisionObservation(scene_description="缓存画面。"),
        identity_name="重岳",
        work_or_affiliation="明日方舟",
        evidence_summary="缓存证据。",
    )
    analyzer = FakeAnalyzer()
    lens = FakeLens([lens_success()])
    store = FakeStore()
    pipeline = make_pipeline(
        analyzer=analyzer,
        lens=lens,
        store=store,
        cache=FakeCache(cached),
    )

    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )

    assert result.resolutions == (cached,)
    assert analyzer.image_calls == 0
    assert lens.urls == []
    assert store.calls == 0


@pytest.mark.asyncio
async def test_pipeline_reuses_partial_observation_and_lens_cache() -> None:
    cached_observation = VisionObservation(
        scene_description="缓存中的银发动画角色。",
        distinctive_features=("银发",),
    )
    cache = FakeCache(cached_observation=cached_observation, cached_lens=lens_success().evidence)
    analyzer = FakeAnalyzer()
    lens = FakeLens([lens_success()])
    store = FakeStore()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, store=store, cache=cache)

    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert result.ok is True
    assert analyzer.image_calls == 0
    assert lens.urls == []
    assert store.calls == 0
    assert cache.put_resolutions == 1


@pytest.mark.asyncio
async def test_pipeline_writes_observation_and_lens_stage_cache() -> None:
    cache = FakeCache()
    pipeline = make_pipeline(cache=cache)

    await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert cache.put_observations == 1
    assert cache.put_lens_results == 1


@pytest.mark.asyncio
async def test_pipeline_hard_deadline_returns_safe_result() -> None:
    pipeline = make_pipeline(analyzer=FakeAnalyzer(delay=1), timeout=0.05)

    started = time.monotonic()
    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="",
    )
    elapsed = time.monotonic() - started
    await pipeline.close()

    assert elapsed < 0.2
    assert result.timed_out is True
    assert result.resolutions[0].confidence is not ConfidenceBand.CONFIRMED


@pytest.mark.asyncio
async def test_pipeline_timeout_preserves_multi_image_positions() -> None:
    pipeline = make_pipeline(timeout=0.05)
    pipeline.preprocessor = PerUrlPreprocessor(
        {
            "https://qq.test/slow.png": 1,
            "https://qq.test/fast.png": 0,
        }
    )

    result = await pipeline.describe(
        ["https://qq.test/slow.png", "https://qq.test/fast.png"],
        user_question="分别是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert result.timed_out is True
    assert result.resolutions[0].confidence is ConfidenceBand.UNCERTAIN
    assert result.resolutions[1].confidence is ConfidenceBand.CONFIRMED


@pytest.mark.asyncio
async def test_pipeline_limits_images_and_keeps_input_order() -> None:
    pipeline = make_pipeline(max_images=2)

    result = await pipeline.describe(
        ["https://qq.test/a.png", "https://qq.test/b.png", "https://qq.test/c.png"],
        user_question="分别是谁？",
        chat_context="",
    )
    await pipeline.close()

    assert len(result.resolutions) == 2
    assert "图片1" in result.context_text
    assert "图片2" in result.context_text
    assert "图片3" not in result.context_text


@pytest.mark.asyncio
async def test_pipeline_dynamic_media_skips_lens_and_r2() -> None:
    analyzer = FakeAnalyzer()
    lens = FakeLens([lens_success()])
    store = FakeStore()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, store=store)

    result = await pipeline.describe(
        [],
        ["https://qq.test/wave.gif"],
        user_question="在干嘛？",
        chat_context="",
    )

    assert result.ok is True
    assert "有人挥手" in result.context_text
    assert analyzer.dynamic_calls == 1
    assert lens.urls == []
    assert store.calls == 0
