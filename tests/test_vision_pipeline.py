from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from qq_rolebot.image_preprocessor import NormalizedImage
from qq_rolebot.vision_pipeline import VisionPipeline
from qq_rolebot.vision_types import (
    ConfidenceBand,
    ExactSearchResult,
    ImageDecision,
    LensAllEvidence,
    LensSearchResult,
    SearchSource,
    VisionObservation,
    VisionSynthesis,
)


def normalized(url: str, *, image_hash: str | None = None) -> NormalizedImage:
    marker = url.rsplit("/", 1)[-1][0]
    return NormalizedImage(
        content=f"image-{marker}".encode(),
        content_type="image/jpeg",
        width=10,
        height=10,
        sha256=image_hash or marker * 64,
        source_url=url.split("?", 1)[0],
    )


def decision(
    image_number: int,
    *,
    confidence: ConfidenceBand = ConfidenceBand.CONFIRMED,
    needs_exact: bool = False,
    needs_web: bool = False,
) -> ImageDecision:
    return ImageDecision(
        image_number=image_number,
        confidence=confidence,
        scene_description=f"图片{image_number}场景",
        subject_identity=f"角色{image_number}" if confidence is ConfidenceBand.CONFIRMED else "",
        work_or_affiliation="作品",
        needs_exact=needs_exact,
        needs_web=needs_web,
        verification_query=f"角色{image_number} 作品",
    )


class FakePreprocessor:
    def __init__(
        self,
        *,
        hashes: dict[str, str] | None = None,
        failures: set[str] | None = None,
    ) -> None:
        self.hashes = hashes or {}
        self.failures = failures or set()
        self.urls: list[str] = []

    async def fetch(self, url, *, trace=None, timeout_seconds=None):
        self.urls.append(url)
        if url in self.failures:
            raise ValueError("synthetic preprocess failure")
        return normalized(url, image_hash=self.hashes.get(url))


class FakeAnalyzer:
    def __init__(self, synthesis: VisionSynthesis | None = None) -> None:
        self.result = synthesis
        self.synthesize_calls = 0
        self.reevaluate_calls = 0
        self.dynamic_calls = 0
        self.closed = 0
        self.images: tuple[NormalizedImage, ...] = ()
        self.lens_results = ()
        self.user_question = ""
        self.chat_context = ""
        self.fallback_results = ()

    async def synthesize(
        self,
        images,
        lens_results,
        *,
        user_question,
        chat_context,
        timeout_seconds,
        trace=None,
    ):
        self.synthesize_calls += 1
        self.images = images
        self.lens_results = lens_results
        self.user_question = user_question
        self.chat_context = chat_context
        if self.result is not None:
            return self.result
        return VisionSynthesis(
            images=tuple(decision(item.image_number) for item in lens_results),
            combined_answer="合成结论",
        )

    async def reevaluate(
        self,
        previous,
        fallback_results,
        *,
        timeout_seconds,
        trace=None,
    ):
        self.reevaluate_calls += 1
        self.fallback_results = fallback_results
        return VisionSynthesis(
            images=tuple(
                replace(item, needs_exact=False, needs_web=False) for item in previous.images
            ),
            combined_answer="复判结论",
        )

    async def describe_dynamic_media(
        self,
        video_urls,
        *,
        user_question,
        timeout_seconds,
        trace=None,
    ):
        self.dynamic_calls += 1
        return VisionObservation(scene_description="有人挥手。")

    async def close(self):
        self.closed += 1


class FakeLens:
    def __init__(self, *, delay: float = 0, failures: set[str] | None = None) -> None:
        self.delay = delay
        self.failures = failures or set()
        self.all_urls: list[str] = []
        self.exact_urls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.closed = 0

    async def search_all(self, url, *, timeout_seconds, trace=None):
        self.all_urls.append(url)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        if url in self.failures:
            return LensSearchResult(ok=False, error="unreachable", unreachable=True)
        source = SearchSource(
            title=f"Lens {url.rsplit('/', 1)[-1]}",
            url="",
            domain="lens.test",
            snippet="synthetic",
            result_kind="visual",
        )
        return LensSearchResult(
            ok=True,
            evidence=LensAllEvidence(visual_matches=(source,)),
        )

    async def search_exact(self, url, *, timeout_seconds, trace=None):
        self.exact_urls.append(url)
        return ExactSearchResult(
            ok=True,
            sources=(
                SearchSource("Exact", "", "exact.test", "synthetic", "exact"),
            ),
        )

    async def close(self):
        self.closed += 1


class FakeWeb:
    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.queries: list[str] = []
        self.closed = 0

    async def search(self, query, *, timeout_seconds, trace=None):
        self.queries.append(query)
        await asyncio.sleep(self.delay)
        return (SearchSource("Web", "", "web.test", "synthetic", "web"),)

    async def close(self):
        self.closed += 1


class FakeCache:
    def __init__(self) -> None:
        self.lens: dict[tuple[str, str], LensSearchResult] = {}
        self.exact: dict[tuple[str, str], ExactSearchResult] = {}
        self.syntheses: dict[str, VisionSynthesis] = {}
        self.put_lens_calls = 0

    async def get_lens_all(self, image_hash, *, version, now):
        return self.lens.get((image_hash, version))

    async def put_lens_all(self, image_hash, *, version, result, now):
        self.put_lens_calls += 1
        if result.ok:
            self.lens[(image_hash, version)] = result

    async def get_exact(self, image_hash, *, version, now):
        return self.exact.get((image_hash, version))

    async def put_exact(self, image_hash, *, version, result, now):
        if result.ok:
            self.exact[(image_hash, version)] = result

    def build_synthesis_key(self, **kwargs):
        return repr(kwargs)

    async def get_synthesis(self, request_hash, *, now):
        return self.syntheses.get(request_hash)

    async def put_synthesis(self, request_hash, *, synthesis, now):
        self.syntheses[request_hash] = synthesis


def make_pipeline(
    *,
    preprocessor=None,
    analyzer=None,
    lens=None,
    web=None,
    cache=None,
    total_timeout=0.5,
    multi_timeout=0.7,
    lens_timeout=0.2,
    concurrency=2,
    max_images=4,
) -> VisionPipeline:
    return VisionPipeline(
        preprocessor=preprocessor or FakePreprocessor(),
        analyzer=analyzer or FakeAnalyzer(),
        lens_client=lens,
        web_client=web,
        cache=cache or FakeCache(),
        total_timeout_seconds=total_timeout,
        multi_timeout_seconds=multi_timeout,
        lens_timeout_seconds=lens_timeout,
        model_timeout_seconds=0.2,
        lens_concurrency=concurrency,
        max_images=max_images,
        exact_fallback_enabled=True,
        web_fallback_enabled=True,
        max_exact_fallbacks=2,
        max_web_fallbacks=2,
        model_name="vision-model",
        prompt_version="prompt-v2",
        lens_parser_version="lens-v2",
        schema_version="schema-v1",
        now=lambda: 100,
    )


@pytest.mark.asyncio
async def test_pipeline_runs_lens_all_then_one_synthesis_without_exact() -> None:
    analyzer = FakeAnalyzer()
    lens = FakeLens()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens)

    result = await pipeline.describe(
        ["https://qq.test/a.png?token=private"],
        user_question="这是谁？",
        chat_context="正在讨论作品",
    )

    assert result.ok is True
    assert analyzer.synthesize_calls == 1
    assert analyzer.user_question == "这是谁？"
    assert analyzer.chat_context == "正在讨论作品"
    assert lens.all_urls == ["https://qq.test/a.png?token=private"]
    assert lens.exact_urls == []
    assert result.synthesis.images[0].confidence is ConfidenceBand.CONFIRMED


@pytest.mark.asyncio
async def test_pipeline_without_lens_still_calls_qwen_for_every_image() -> None:
    analyzer = FakeAnalyzer()
    pipeline = make_pipeline(analyzer=analyzer, lens=None)

    result = await pipeline.describe(
        ["https://qq.test/a.png", "https://qq.test/b.png"],
        user_question="分别是什么？",
        chat_context="",
    )

    assert result.ok is True
    assert [item.image_number for item in analyzer.lens_results] == [1, 2]
    assert all(not item.search.ok for item in analyzer.lens_results)


@pytest.mark.asyncio
async def test_pipeline_runs_bounded_exact_and_web_then_one_reevaluation() -> None:
    initial = VisionSynthesis(
        images=tuple(
            decision(index, confidence=ConfidenceBand.UNCERTAIN, needs_exact=True, needs_web=True)
            for index in range(1, 4)
        )
    )
    analyzer = FakeAnalyzer(initial)
    lens = FakeLens()
    web = FakeWeb()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, web=web)

    result = await pipeline.describe(
        [f"https://qq.test/{name}.png" for name in ("a", "b", "c")],
        user_question="分别是谁？",
        chat_context="",
    )

    assert result.ok is True
    assert len(lens.exact_urls) == 2
    assert len(web.queries) == 2
    assert analyzer.reevaluate_calls == 1
    assert {item.image_number for item in analyzer.fallback_results} == {1, 2}
    assert result.synthesis.combined_answer == "复判结论"


@pytest.mark.asyncio
async def test_pipeline_handles_four_images_deduplicates_lens_and_limits_concurrency() -> None:
    urls = [f"https://qq.test/{name}.png" for name in ("a", "b", "c", "d", "e")]
    preprocessor = FakePreprocessor(hashes={urls[1]: "a" * 64})
    analyzer = FakeAnalyzer()
    lens = FakeLens(delay=0.01)
    pipeline = make_pipeline(preprocessor=preprocessor, analyzer=analyzer, lens=lens)

    result = await pipeline.describe(urls, user_question="比较这些图", chat_context="")

    assert len(analyzer.images) == 4
    assert [item.image_number for item in analyzer.lens_results] == [1, 2, 3, 4]
    assert len(lens.all_urls) == 3
    assert lens.max_active <= 2
    assert "另有 1 张图片未进入识图" in result.context_text


@pytest.mark.asyncio
async def test_pipeline_preserves_position_when_one_preprocess_fails() -> None:
    failed = "https://qq.test/b.png"
    analyzer = FakeAnalyzer()
    pipeline = make_pipeline(
        preprocessor=FakePreprocessor(failures={failed}),
        analyzer=analyzer,
        lens=FakeLens(),
    )

    result = await pipeline.describe(
        ["https://qq.test/a.png", failed, "https://qq.test/c.png"],
        user_question="分别是谁？",
        chat_context="",
    )

    assert [item.image_number for item in analyzer.lens_results] == [1, 3]
    assert [item.image_number for item in result.synthesis.images] == [1, 2, 3]
    assert result.synthesis.images[1].confidence is ConfidenceBand.UNAVAILABLE
    assert result.synthesis.images[2].confidence is ConfidenceBand.CONFIRMED


@pytest.mark.asyncio
async def test_combined_cache_hit_skips_lens_and_qwen() -> None:
    cache = FakeCache()
    analyzer = FakeAnalyzer()
    lens = FakeLens()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, cache=cache)
    first = await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    second = await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    assert second.synthesis == first.synthesis
    assert analyzer.synthesize_calls == 1
    assert len(lens.all_urls) == 1


@pytest.mark.asyncio
async def test_lens_cache_hit_still_runs_qwen_for_a_new_question() -> None:
    cache = FakeCache()
    analyzer = FakeAnalyzer()
    lens = FakeLens()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, cache=cache)
    await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    await pipeline.describe(
        ["https://qq.test/a.png"], user_question="来自什么作品？", chat_context=""
    )

    assert analyzer.synthesize_calls == 2
    assert len(lens.all_urls) == 1


@pytest.mark.asyncio
async def test_concurrent_same_hash_requests_share_one_inflight_lens_task() -> None:
    lens = FakeLens(delay=0.05)
    pipeline = make_pipeline(lens=lens)

    await asyncio.gather(
        pipeline.describe(
            ["https://qq.test/a.png"], user_question="问题一", chat_context=""
        ),
        pipeline.describe(
            ["https://qq.test/a.png"], user_question="问题二", chat_context=""
        ),
    )

    assert len(lens.all_urls) == 1


@pytest.mark.asyncio
async def test_lens_stage_timeout_keeps_qwen_path_available() -> None:
    analyzer = FakeAnalyzer()
    lens = FakeLens(delay=0.2)
    pipeline = make_pipeline(
        analyzer=analyzer,
        lens=lens,
        total_timeout=0.15,
        lens_timeout=0.02,
    )

    result = await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    assert result.ok is True
    assert analyzer.synthesize_calls == 1
    assert analyzer.lens_results[0].search.ok is False


@pytest.mark.asyncio
async def test_fallback_timeout_preserves_first_qwen_result() -> None:
    initial = VisionSynthesis(
        images=(
            decision(
                1,
                confidence=ConfidenceBand.UNCERTAIN,
                needs_web=True,
            ),
        ),
        combined_answer="首次判断仍不确定",
    )
    analyzer = FakeAnalyzer(initial)
    pipeline = make_pipeline(
        analyzer=analyzer,
        lens=None,
        web=FakeWeb(delay=0.2),
        total_timeout=0.05,
        lens_timeout=0.01,
    )

    result = await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    assert result.synthesis.images[0].confidence is ConfidenceBand.UNCERTAIN
    assert result.synthesis.combined_answer == "首次判断仍不确定"


@pytest.mark.asyncio
async def test_dynamic_media_is_described_without_lens() -> None:
    analyzer = FakeAnalyzer()
    lens = FakeLens()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens)

    result = await pipeline.describe(
        [],
        ["https://qq.test/wave.gif"],
        user_question="在干嘛？",
        chat_context="",
    )

    assert result.ok is True
    assert "有人挥手" in result.context_text
    assert analyzer.dynamic_calls == 1
    assert lens.all_urls == []


@pytest.mark.asyncio
async def test_close_waits_inflight_tasks_and_closes_provider_clients() -> None:
    analyzer = FakeAnalyzer()
    lens = FakeLens(delay=0.05)
    web = FakeWeb()
    pipeline = make_pipeline(analyzer=analyzer, lens=lens, web=web, lens_timeout=0.01)
    await pipeline.describe(
        ["https://qq.test/a.png"], user_question="这是谁？", chat_context=""
    )

    await pipeline.close()

    assert analyzer.closed == 1
    assert lens.closed == 1
    assert web.closed == 1
