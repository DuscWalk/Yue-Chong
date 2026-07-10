# Evidence-Driven Vision Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace opaque Qwen built-in image/web search with a structured, conservative vision pipeline that combines visual analysis, SerpApi Google Lens, SerpApi Google Search, Cloudflare R2 temporary publication, caching, and one configurable total deadline.

**Architecture:** `VisionPipeline` becomes the single service-facing coordinator. Focused modules own normalized image preparation, schema-constrained visual analysis, SerpApi clients, temporary R2 publication, evidence resolution, and cache persistence; the pipeline runs independent work concurrently and passes only confirmed or explicitly uncertain context to the existing roleplay model. Static images use the full evidence pipeline, while existing GIF/video inputs retain visual-description fallback without reverse-image search in the first release.

**Tech Stack:** Python 3.11, asyncio, httpx, Pillow, boto3/botocore, SQLite via aiosqlite, pytest/pytest-asyncio, Ruff.

---

## File Structure

- Create `qq_rolebot/vision_types.py`: immutable records and enums shared by every vision stage.
- Create `qq_rolebot/image_preprocessor.py`: bounded image download, decode, normalize, and hashing.
- Rewrite `qq_rolebot/vision_client.py`: schema-constrained visual analyzer only; retain dynamic-media description support.
- Create `qq_rolebot/serpapi_client.py`: Google Lens and Google Search HTTP clients plus response normalization.
- Create `qq_rolebot/temp_image_store.py`: provider-neutral temporary image store protocol and Cloudflare R2 implementation.
- Create `qq_rolebot/vision_resolver.py`: deterministic candidate merging, source independence, and conservative identity rules.
- Create `qq_rolebot/vision_cache.py`: SQLite-backed versioned cache for observations, Lens results, and resolutions.
- Create `qq_rolebot/vision_pipeline.py`: total deadline, concurrency, fallback, cache, tracing, and cleanup orchestration.
- Modify `qq_rolebot/config.py`: replace obsolete search-mode settings with pipeline, SerpApi, R2, and safety limits.
- Modify `qq_rolebot/service.py`: pass the user's question and bounded recent context into the pipeline and format confirmed versus uncertain results safely.
- Modify `qq_rolebot/plugins/roleplay_chat.py`: construct and inject the new components only when the feature is fully configured.
- Modify `pyproject.toml`: add Pillow and boto3 runtime dependencies.
- Replace `tests/test_vision_client.py`: visual-analyzer payload, structured parsing, and dynamic-media fallback tests.
- Create `tests/test_image_preprocessor.py`, `tests/test_serpapi_client.py`, `tests/test_temp_image_store.py`, `tests/test_vision_resolver.py`, `tests/test_vision_cache.py`, and `tests/test_vision_pipeline.py`.
- Create sanitized fixtures under `tests/fixtures/serpapi/` for Lens and Google Search parser contract tests.
- Modify `tests/test_config.py`, `tests/test_service.py`, and `tests/test_plugin_smoke.py` for wiring and behavioral regression coverage.
- Modify `.env.example`, `README.md`, and `docs/deployment.md` for setup, privacy, R2 lifecycle, and diagnostics.
- Create `scripts/summarize_vision_traces.py` and `tests/test_summarize_vision_traces.py` for offline latency and decision statistics.

### Task 1: Define Vision Evidence Types

**Files:**
- Create: `qq_rolebot/vision_types.py`
- Test: `tests/test_vision_types.py`

- [ ] **Step 1: Write failing serialization and context-format tests**

```python
from qq_rolebot.vision_types import (
    ConfidenceBand,
    IdentityCandidate,
    VisionObservation,
    VisionResolution,
)


def test_uncertain_resolution_forbids_candidate_as_fact() -> None:
    resolution = VisionResolution(
        confidence=ConfidenceBand.UNCERTAIN,
        observation=VisionObservation(
            scene_description="一名银发动画角色站在雪地里。",
            visible_text=("RHODES",),
            people_or_characters=("动画角色",),
            distinctive_features=("银发", "黑色外套"),
        ),
        candidates=(
            IdentityCandidate(
                name="候选角色",
                entity_type="fictional_character",
                work_or_affiliation="候选作品",
                visual_reason="外观相似",
                source_stage="visual",
            ),
        ),
        confirmed_identity=None,
        evidence_summary="只有视觉相似，没有外部证据。",
        uncertainty_reason="证据不足",
    )

    text = resolution.to_context_text(image_number=1)

    assert "身份判断：无法可靠确认" in text
    assert "候选角色" not in text
    assert "请勿猜测具体身份" in text


def test_confirmed_resolution_includes_verified_identity() -> None:
    resolution = VisionResolution.confirmed(
        observation=VisionObservation(scene_description="动画角色特写。"),
        identity_name="重岳",
        work_or_affiliation="明日方舟",
        evidence_summary="相同图片结果与官方角色页一致。",
    )

    text = resolution.to_context_text(image_number=2)

    assert "图片2" in text
    assert "《明日方舟》中的“重岳”" in text
    assert "相同图片结果与官方角色页一致" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'qq_rolebot.vision_types'`.

- [ ] **Step 3: Implement immutable shared types**

Create enums/dataclasses with these public fields and helpers:

```python
class ConfidenceBand(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VisionObservation:
    scene_description: str = ""
    visible_text: tuple[str, ...] = ()
    people_or_characters: tuple[str, ...] = ()
    distinctive_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityCandidate:
    name: str
    entity_type: str
    work_or_affiliation: str = ""
    visual_reason: str = ""
    source_stage: str = ""


@dataclass(frozen=True)
class SearchSource:
    title: str
    url: str
    domain: str
    snippet: str = ""
    result_kind: str = ""


@dataclass(frozen=True)
class LensEvidence:
    exact_matches: tuple[SearchSource, ...] = ()
    visual_matches: tuple[SearchSource, ...] = ()
    repeated_entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateWebEvidence:
    candidate_name: str
    supporting_sources: tuple[SearchSource, ...] = ()
    contradicting_sources: tuple[SearchSource, ...] = ()


@dataclass(frozen=True)
class VisionResolution:
    confidence: ConfidenceBand
    observation: VisionObservation
    candidates: tuple[IdentityCandidate, ...] = ()
    confirmed_identity: IdentityCandidate | None = None
    evidence_summary: str = ""
    uncertainty_reason: str = ""

    def to_context_text(self, *, image_number: int) -> str: ...
```

`to_context_text()` must never include candidate names when confidence is not `CONFIRMED`. Add `confirmed()`, `uncertain()`, and `unavailable()` constructors so later tasks use one consistent API.

- [ ] **Step 4: Run focused tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_types.py tests/test_vision_types.py
git commit -m "feat: define structured vision evidence types"
```

### Task 2: Add Pipeline Configuration And Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `qq_rolebot/config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing configuration tests**

Add tests that assert these defaults:

```python
def test_load_settings_reads_vision_pipeline_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.vision_pipeline_timeout_seconds == 15.0
    assert settings.vision_pipeline_max_images == 2
    assert settings.vision_pipeline_cache_ttl_seconds == 86_400
    assert settings.vision_pipeline_max_download_bytes == 10_485_760
    assert settings.vision_pipeline_max_image_pixels == 20_000_000
    assert settings.vision_model_timeout_seconds == 8.0
    assert settings.vision_model_enable_thinking is False
    assert settings.serpapi_lens_enabled is True
    assert settings.serpapi_search_enabled is True
    assert settings.serpapi_timeout_seconds == 8.0
    assert settings.serpapi_lens_exact_limit == 5
    assert settings.serpapi_lens_visual_limit == 10
    assert settings.serpapi_web_candidate_limit == 2
    assert settings.vision_temp_store_backend == "r2"
    assert settings.r2_presigned_url_seconds == 300
    assert settings.r2_object_prefix == "vision-temp/"
```

Add validation tests for nonpositive deadline, image count, download bytes, pixel count, SerpApi limits, signed-URL lifetime, and unsupported temp-store backend. Add a regression assertion that `Settings` no longer exposes `vision_model_mode`, `vision_model_search_input`, `vision_model_enable_search`, or `vision_model_search_timeout_seconds`.

- [ ] **Step 2: Run configuration tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_config.py
```

Expected: FAIL because the new settings fields do not exist.

- [ ] **Step 3: Add dependencies and settings**

Add runtime dependencies:

```toml
"Pillow>=10.4.0",
"boto3>=1.34.0",
```

Replace obsolete vision-search settings with:

```python
vision_pipeline_timeout_seconds: float
vision_pipeline_max_images: int
vision_pipeline_cache_ttl_seconds: int
vision_pipeline_max_download_bytes: int
vision_pipeline_max_image_pixels: int
serpapi_api_key: str
serpapi_lens_enabled: bool
serpapi_search_enabled: bool
serpapi_timeout_seconds: float
serpapi_lens_exact_limit: int
serpapi_lens_visual_limit: int
serpapi_web_candidate_limit: int
vision_temp_store_backend: str
r2_account_id: str
r2_access_key_id: str
r2_secret_access_key: str
r2_bucket: str
r2_presigned_url_seconds: int
r2_object_prefix: str
vision_cache_path: Path
```

Use `data/vision_cache.sqlite3` as the default cache path. Update `.env.example` with placeholders only, and remove `VISION_MODEL_MODE`, `VISION_MODEL_SEARCH_INPUT`, `VISION_MODEL_ENABLE_SEARCH`, and `VISION_MODEL_SEARCH_TIMEOUT_SECONDS`.

- [ ] **Step 4: Install dependencies in the dedicated environment and run tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pip install -e '.[dev]'
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_config.py
```

Expected: installation succeeds and configuration tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml qq_rolebot/config.py tests/test_config.py .env.example
git commit -m "feat: configure evidence vision pipeline"
```

### Task 3: Implement Safe Image Preprocessing

**Files:**
- Create: `qq_rolebot/image_preprocessor.py`
- Create: `tests/test_image_preprocessor.py`

- [ ] **Step 1: Write failing preprocessing tests**

Use generated in-memory Pillow images and `httpx.MockTransport` to cover:

```python
@pytest.mark.asyncio
async def test_preprocessor_normalizes_and_hashes_image() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        transport=transport_returning_png(width=32, height=16),
    )

    image = await preprocessor.fetch("https://qq.test/image?id=secret")

    assert image.content_type == "image/png"
    assert image.width == 32
    assert image.height == 16
    assert len(image.sha256) == 64
    assert image.source_url == "https://qq.test/image"


@pytest.mark.asyncio
async def test_preprocessor_rejects_oversized_download() -> None:
    ...
    with pytest.raises(ImagePreprocessError, match="download exceeds"):
        await preprocessor.fetch("https://qq.test/large")


@pytest.mark.asyncio
async def test_preprocessor_rejects_pixel_bomb() -> None:
    ...
    with pytest.raises(ImagePreprocessError, match="pixel limit"):
        await preprocessor.fetch("https://qq.test/huge.png")
```

Also test unsupported content, invalid bytes, redirect limits, EXIF orientation, animated GIF rejection from the static path, and trace URL query redaction.

- [ ] **Step 2: Run preprocessing tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_image_preprocessor.py
```

Expected: FAIL with missing module/classes.

- [ ] **Step 3: Implement bounded preprocessing**

Expose:

```python
@dataclass(frozen=True)
class NormalizedImage:
    content: bytes
    content_type: str
    width: int
    height: int
    sha256: str
    source_url: str

    def data_url(self) -> str: ...


class ImagePreprocessor:
    async def fetch(
        self,
        url: str,
        *,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> NormalizedImage: ...
```

Stream response bytes and stop immediately after `max_download_bytes`. Decode with Pillow, call `ImageOps.exif_transpose`, reject multi-frame images from this static path, convert unsupported color modes to RGB/RGBA, and encode as PNG unless a safe JPEG can be retained. Store only the URL without query/fragment in `source_url` and traces.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_image_preprocessor.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/image_preprocessor.py tests/test_image_preprocessor.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/image_preprocessor.py tests/test_image_preprocessor.py
git commit -m "feat: preprocess vision images safely"
```

### Task 4: Rewrite The Visual Analyzer

**Files:**
- Rewrite: `qq_rolebot/vision_client.py`
- Replace: `tests/test_vision_client.py`

- [ ] **Step 1: Write failing structured analyzer tests**

Test a request shaped like:

```python
result = await analyzer.analyze_image(
    normalized_image,
    user_question="这是谁？",
    chat_context="用户刚才在讨论明日方舟。",
)

assert result.observation.scene_description == "一名银发男性动画角色。"
assert result.observation.visible_text == ("炎国",)
assert result.candidates[0].name == "重岳"
```

Assert the payload includes the actual user question, bounded chat context, a JSON schema request, the image data URL, `temperature=0`, and configured `enable_thinking`. Add malformed JSON and timeout tests that return a typed analyzer failure instead of fabricated observations.

Add a separate regression test:

```python
result = await analyzer.describe_dynamic_media(
    ["https://example.test/wave.gif"],
    user_question="这个动图在干嘛？",
)
assert result.scene_description == "有人挥手。"
```

The dynamic-media path must not expose identity as confirmed evidence and must not invoke Lens.

Add a search-evidence extraction test:

```python
result = await analyzer.extract_search_candidates(
    lens_evidence,
    observation=visual_analysis.observation,
    user_question="这是谁？",
)

assert result == (
    IdentityCandidate(
        name="重岳",
        entity_type="fictional_character",
        work_or_affiliation="明日方舟",
        visual_reason="多个 Lens 标题重复出现该角色与作品",
        source_stage="lens_extraction",
    ),
)
```

The extraction request receives only bounded, normalized Lens titles/domains/snippets. It must not
receive full provider responses, signed URLs, or API keys.

- [ ] **Step 2: Run analyzer tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_client.py
```

Expected: FAIL because `analyze_image` and structured response types do not exist.

- [ ] **Step 3: Replace the mixed client with `VisualAnalyzer`**

Implement:

```python
@dataclass(frozen=True)
class VisualAnalysis:
    observation: VisionObservation
    candidates: tuple[IdentityCandidate, ...] = ()
    error: str = ""


class VisualAnalyzer:
    async def analyze_image(
        self,
        image: NormalizedImage,
        *,
        user_question: str,
        chat_context: str,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> VisualAnalysis: ...

    async def describe_dynamic_media(
        self,
        video_urls: list[str],
        *,
        user_question: str,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> VisionObservation: ...

    async def extract_search_candidates(
        self,
        lens: LensEvidence,
        *,
        observation: VisionObservation,
        user_question: str,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[IdentityCandidate, ...]: ...
```

Delete the Responses API `image_search`/`web_search` code and all old hybrid/search-only/media-only behavior. Parse schema output defensively, truncate user/chat text, and redact data URLs from traces.
Search-result extraction is schema constrained and may propose candidates, but it cannot confirm
them; the deterministic resolver remains the only confirmation authority.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_client.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_client.py tests/test_vision_client.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_client.py tests/test_vision_client.py
git commit -m "feat: add structured visual analyzer"
```

### Task 5: Add SerpApi Lens And Web Search Clients

**Files:**
- Create: `qq_rolebot/serpapi_client.py`
- Create: `tests/test_serpapi_client.py`
- Create: `tests/fixtures/serpapi/google_lens.json`
- Create: `tests/fixtures/serpapi/google_search.json`

- [ ] **Step 1: Add sanitized contract fixtures and failing parser tests**

Fixtures must contain only the fields consumed by code. Cover exact matches, visual matches, duplicate domains, a repeated character/work name, organic results, and a conflicting result.

```python
def test_parse_lens_response_normalizes_and_limits_results() -> None:
    evidence = parse_lens_response(
        load_fixture("google_lens.json"),
        exact_limit=2,
        visual_limit=3,
    )

    assert len(evidence.exact_matches) == 2
    assert len(evidence.visual_matches) == 3
    assert evidence.exact_matches[0].domain == "arknights.global"
    assert evidence.repeated_entities == ("重岳", "明日方舟")


@pytest.mark.asyncio
async def test_google_lens_uses_original_image_url() -> None:
    ...
    assert request.url.params["engine"] == "google_lens"
    assert request.url.params["url"] == "https://public.test/image.png"
```

Also test SerpApi error objects, HTTP errors, timeouts, URL canonicalization, tracking removal, same-domain collapse, and API-key redaction.

- [ ] **Step 2: Run SerpApi tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_serpapi_client.py
```

Expected: FAIL with missing parser/client.

- [ ] **Step 3: Implement focused SerpApi clients**

Expose:

```python
class SerpApiLensClient:
    async def search(
        self,
        image_url: str,
        *,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> LensSearchResult: ...


class SerpApiWebClient:
    async def verify(
        self,
        candidate: IdentityCandidate,
        *,
        visual_features: tuple[str, ...],
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> CandidateWebEvidence: ...
```

Use `https://serpapi.com/search.json`, pass API keys only as request parameters, and omit keys from traces. `verify()` builds one bounded query from candidate name, work/affiliation, and at most two distinctive features. Do not expose a generic free-form search method to the pipeline.

- [ ] **Step 4: Run parser/client tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_serpapi_client.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/serpapi_client.py tests/test_serpapi_client.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/serpapi_client.py tests/test_serpapi_client.py tests/fixtures/serpapi
git commit -m "feat: add serpapi vision evidence clients"
```

### Task 6: Add Cloudflare R2 Temporary Image Store

**Files:**
- Create: `qq_rolebot/temp_image_store.py`
- Create: `tests/test_temp_image_store.py`

- [ ] **Step 1: Write failing store tests with a fake S3 client**

```python
@pytest.mark.asyncio
async def test_r2_store_uploads_signs_and_deletes() -> None:
    s3 = FakeS3Client()
    store = R2TemporaryImageStore(
        bucket="private-vision",
        object_prefix="vision-temp/",
        presigned_url_seconds=300,
        s3_client=s3,
    )

    handle = await store.publish(normalized_image)
    await handle.delete()

    assert s3.put_calls[0]["Bucket"] == "private-vision"
    assert s3.put_calls[0]["ContentType"] == "image/png"
    assert handle.url.startswith("https://signed.test/")
    assert "original-name" not in handle.object_key
    assert s3.delete_calls == [("private-vision", handle.object_key)]
```

Add tests for idempotent deletion, upload failure, signing failure cleanup, async cancellation cleanup, and trace output that contains only bucket/object status and never the signed URL.

- [ ] **Step 2: Run store tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_temp_image_store.py
```

Expected: FAIL with missing module/classes.

- [ ] **Step 3: Implement the protocol and R2 backend**

Expose:

```python
class TemporaryImageHandle(Protocol):
    url: str
    object_key: str

    async def delete(self) -> None: ...


class TemporaryImageStore(Protocol):
    async def publish(
        self,
        image: NormalizedImage,
        *,
        trace: DebugTrace | None = None,
    ) -> TemporaryImageHandle: ...
```

Create the boto3 S3 client with endpoint
`https://{account_id}.r2.cloudflarestorage.com`. Run blocking boto3 calls through
`asyncio.to_thread`. Use `secrets.token_urlsafe()` plus the normalized extension for object keys.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_temp_image_store.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/temp_image_store.py tests/test_temp_image_store.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/temp_image_store.py tests/test_temp_image_store.py
git commit -m "feat: publish temporary vision images to r2"
```

### Task 7: Implement Conservative Evidence Resolution

**Files:**
- Create: `qq_rolebot/vision_resolver.py`
- Create: `tests/test_vision_resolver.py`

- [ ] **Step 1: Write a failing decision table**

Use parametrized tests for these required outcomes:

```python
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("visual_only", ConfidenceBand.UNCERTAIN),
        ("one_weak_repost", ConfidenceBand.UNCERTAIN),
        ("conflicting_lens", ConfidenceBand.UNCERTAIN),
        ("same_domain_duplicates", ConfidenceBand.UNCERTAIN),
        ("exact_plus_independent_official", ConfidenceBand.CONFIRMED),
        ("repeated_lens_plus_web_support", ConfidenceBand.CONFIRMED),
        ("cosplay_conflict", ConfidenceBand.UNCERTAIN),
        ("private_person_social_match", ConfidenceBand.UNCERTAIN),
    ],
)
def test_resolver_policy(case: str, expected: ConfidenceBand) -> None:
    resolution = resolver.resolve(**fixture_case(case))
    assert resolution.confidence is expected
```

Assert confirmed resolutions include a stable rule identifier such as `exact_independent_support`, while uncertain resolutions include a rejection reason. Add candidate merge tests that normalize whitespace/case but never merge different works solely from similar names.

- [ ] **Step 2: Run resolver tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_resolver.py
```

Expected: FAIL with missing resolver.

- [ ] **Step 3: Implement deterministic resolution**

Expose:

```python
@dataclass(frozen=True)
class ResolverDecision:
    resolution: VisionResolution
    rule_id: str


class VisionEvidenceResolver:
    def select_web_candidates(
        self,
        visual_candidates: tuple[IdentityCandidate, ...],
        lens: LensEvidence,
        *,
        limit: int,
    ) -> tuple[IdentityCandidate, ...]: ...

    def resolve(
        self,
        *,
        observation: VisionObservation,
        visual_candidates: tuple[IdentityCandidate, ...],
        lens: LensEvidence,
        web_evidence: tuple[CandidateWebEvidence, ...],
    ) -> ResolverDecision: ...
```

Encode confirmation rules as named pure functions. Treat domains as independent only after canonicalization. Add a private-person guard based on entity type and absence of reliable public-context evidence. Never use model numeric confidence as a confirmation threshold.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_resolver.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_resolver.py tests/test_vision_resolver.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_resolver.py tests/test_vision_resolver.py
git commit -m "feat: resolve vision identity conservatively"
```

### Task 8: Add Versioned Vision Cache

**Files:**
- Create: `qq_rolebot/vision_cache.py`
- Create: `tests/test_vision_cache.py`

- [ ] **Step 1: Write failing cache tests**

```python
@pytest.mark.asyncio
async def test_resolution_cache_requires_matching_version(tmp_path: Path) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=86_400)
    await cache.init()
    await cache.put_resolution("abc", version="v1", resolution=confirmed_resolution(), now=100)

    assert await cache.get_resolution("abc", version="v1", now=200) is not None
    assert await cache.get_resolution("abc", version="v2", now=200) is None


@pytest.mark.asyncio
async def test_cache_expires_without_storing_image_or_signed_url(tmp_path: Path) -> None:
    ...
```

Cover observation, Lens, and final-resolution layers; TTL pruning; corrupted JSON; and schema round trips. Inspect the SQLite file content or rows to assert no raw image bytes, data URLs, signed URLs, or provider API keys are stored.

- [ ] **Step 2: Run cache tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_cache.py
```

Expected: FAIL with missing cache.

- [ ] **Step 3: Implement SQLite cache**

Use one table:

```sql
CREATE TABLE IF NOT EXISTS vision_cache (
    image_hash TEXT NOT NULL,
    stage TEXT NOT NULL,
    version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (image_hash, stage, version)
);
```

Expose typed `get_observation`, `put_observation`, `get_lens`, `put_lens`, `get_resolution`, and `put_resolution` methods. Serialize only the shared dataclasses. Prune expired rows during writes and initialization.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_cache.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_cache.py tests/test_vision_cache.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_cache.py tests/test_vision_cache.py
git commit -m "feat: cache structured vision evidence"
```

### Task 9: Build The Deadline-Controlled Vision Pipeline

**Files:**
- Create: `qq_rolebot/vision_pipeline.py`
- Create: `tests/test_vision_pipeline.py`

- [ ] **Step 1: Write failing orchestration tests with fakes**

Required tests:

```python
@pytest.mark.asyncio
async def test_pipeline_runs_visual_and_publication_concurrently() -> None:
    ...
    result = await pipeline.describe(
        ["https://qq.test/a.png"],
        user_question="这是谁？",
        chat_context="最近在聊明日方舟。",
    )
    assert clock.elapsed < serial_duration
    assert result.resolutions[0].confidence is ConfidenceBand.CONFIRMED


@pytest.mark.asyncio
async def test_pipeline_uses_r2_only_after_original_lens_fetch_failure() -> None:
    ...
    assert lens.urls == ["https://qq.test/a.png", "https://signed.test/fallback"]


@pytest.mark.asyncio
async def test_pipeline_hard_deadline_returns_completed_safe_evidence() -> None:
    ...
    assert elapsed < 0.3
    assert result.timed_out is True
    assert result.resolutions[0].confidence is ConfidenceBand.UNCERTAIN
```

Also cover complete-resolution cache hits skipping every provider; partial cache reuse; maximum two images; independent image labels; web verification limited to two candidates; insufficient remaining budget skipping optional web search; Lens success preventing duplicate fallback search; R2 deletion after success/failure/timeout; visual-only fallback; all-provider failure; and dynamic-media description without Lens/R2.

- [ ] **Step 2: Run pipeline tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_pipeline.py
```

Expected: FAIL with missing pipeline.

- [ ] **Step 3: Implement one-deadline orchestration**

Expose the service-facing API:

```python
@dataclass(frozen=True)
class VisionPipelineResult:
    ok: bool
    context_text: str
    resolutions: tuple[VisionResolution, ...] = ()
    timed_out: bool = False
    error: str = ""


class VisionPipeline:
    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
        *,
        user_question: str,
        chat_context: str,
        trace: DebugTrace | None = None,
    ) -> VisionPipelineResult: ...
```

Use `asyncio.timeout(total_timeout)` around the pipeline, compute a monotonic absolute deadline, and pass `remaining_seconds()` to components. For each selected image:

1. preprocess;
2. check final cache;
3. start visual analysis and R2 publication concurrently;
4. start Lens with original URL;
5. retry Lens with the signed R2 URL only for a fetch/unreachable result and sufficient remaining time;
6. ask the analyzer to extract structured candidates from bounded normalized Lens evidence;
7. merge visual and Lens-derived candidates;
8. verify at most configured candidate count concurrently;
9. resolve and cache;
10. delete any R2 object in a tracked shielded best-effort cleanup task.

`VisionPipeline` owns a `set[asyncio.Task[None]]` for cleanup tasks, removes finished tasks through a
done callback, and exposes `async close()` so application shutdown can await remaining deletions.
Never create an unreferenced fire-and-forget deletion task.

Join image contexts in input order. For videos/GIF URLs, call only `describe_dynamic_media()` and append an explicitly non-identity-confirming observation.

- [ ] **Step 4: Run focused tests and Ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_pipeline.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_pipeline.py tests/test_vision_pipeline.py
```

Expected: both commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_pipeline.py tests/test_vision_pipeline.py
git commit -m "feat: orchestrate deadline-bound vision evidence"
```

### Task 10: Integrate Service And Plugin Wiring

**Files:**
- Modify: `qq_rolebot/service.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing service behavior tests**

Update the fake protocol to require:

```python
async def describe(
    self,
    image_urls: list[str],
    video_urls: list[str] | None = None,
    *,
    user_question: str,
    chat_context: str,
    trace=None,
): ...
```

Add assertions that:

- the current user question reaches the pipeline;
- recent chat context reaches the pipeline but is bounded;
- an uncertain pipeline context contains `无法可靠确认` and never an unconfirmed candidate name;
- a confirmed context reaches the main model intact;
- non-triggering group images still do not call the pipeline;
- private and addressed group images do call it;
- stored follow-up context keeps the existing conversation scoping;
- pipeline failure preserves text fallback;
- videos still receive dynamic-media context.

Add plugin smoke tests for component construction when all required settings exist and for clean disablement when SerpApi or R2 credentials are missing.

- [ ] **Step 2: Run service and plugin tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_service.py tests/test_plugin_smoke.py
```

Expected: FAIL because the service uses the old vision protocol and plugin creates `VisionClient` directly.

- [ ] **Step 3: Wire the new pipeline**

Change `VisionClientProtocol` to the new keyword-only question/context signature. In `_vision_context()`, retrieve recent messages before the pipeline call, format a bounded plain-text context, and pass `message.text` as `user_question`.

In `roleplay_chat.py`, construct:

```python
preprocessor = ImagePreprocessor(...)
analyzer = VisualAnalyzer(...)
lens_client = SerpApiLensClient(...)
web_client = SerpApiWebClient(...)
store = R2TemporaryImageStore(...)
cache = VisionCache(...)
resolver = VisionEvidenceResolver()
vision_pipeline = VisionPipeline(...)
```

Initialize the cache during NoneBot startup. If `VISION_MODEL_ENABLED=true` but required model,
SerpApi, or R2 values are incomplete, log a sanitized configuration error and leave vision disabled;
do not start a partially configured evidence pipeline.

Register a NoneBot shutdown hook that awaits `vision_pipeline.close()` and closes reusable HTTP
clients if the concrete implementation owns them.

Update the main-model vision instruction constant so it explicitly says uncertain candidates must not
be converted into facts.

- [ ] **Step 4: Run integration-focused tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_service.py tests/test_plugin_smoke.py tests/test_message_segments.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/service.py qq_rolebot/plugins/roleplay_chat.py tests/test_service.py tests/test_plugin_smoke.py
```

Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/service.py qq_rolebot/plugins/roleplay_chat.py tests/test_service.py tests/test_plugin_smoke.py
git commit -m "feat: integrate evidence vision pipeline"
```

### Task 11: Add Trace Aggregation And Documentation

**Files:**
- Create: `scripts/summarize_vision_traces.py`
- Create: `tests/test_summarize_vision_traces.py`
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Write failing trace-summary tests**

Use sanitized JSONL events:

```python
def test_summarizer_reports_latency_and_decision_metrics(tmp_path: Path) -> None:
    write_trace(tmp_path, durations=[1000, 2000, 9000], confirmed=1, uncertain=2, cache_hits=1)

    summary = summarize_trace_dir(tmp_path)

    assert summary["count"] == 3
    assert summary["p50_ms"] == 2000
    assert summary["p95_ms"] == 9000
    assert summary["confirmed"] == 1
    assert summary["uncertain"] == 2
    assert summary["cache_hits"] == 1
```

Test missing fields, malformed lines, provider failures, Lens contribution, web contribution, timeout
count, and output that contains no URLs or trace payload bodies.

- [ ] **Step 2: Run summary tests to verify failure**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_summarize_vision_traces.py
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement the offline summarizer and update docs**

The script accepts a trace directory and prints JSON or a compact table containing count, P50/P90/P95,
stage success/timeout rates, cache hits, confirmed/uncertain/unavailable counts, and Lens/web evidence
contribution. It reads only named numeric/status fields and never echoes event payloads.

Update documentation with:

- the new evidence flow and conservative identity policy;
- the 15-second configurable vision-only budget;
- SerpApi setup without real keys;
- Cloudflare R2 private bucket and one-day `vision-temp/` lifecycle rule;
- signed URL and user-image privacy behavior;
- startup configuration requirements;
- a diagnostic command for the trace summarizer;
- the real 20–50 image evaluation procedure;
- removal of the obsolete Qwen built-in search settings.

- [ ] **Step 4: Run focused docs/script validation**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_summarize_vision_traces.py tests/test_config.py
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check scripts/summarize_vision_traces.py tests/test_summarize_vision_traces.py
git diff --check
```

Expected: all commands PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/summarize_vision_traces.py tests/test_summarize_vision_traces.py README.md docs/deployment.md
git commit -m "docs: add vision pipeline operations guide"
```

### Task 12: Full Verification And Real-Service Probe Guide

**Files:**
- Modify only if verification reveals task-related defects.

- [ ] **Step 1: Run the complete static and test suite**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

Expected: Ruff reports no errors, pytest reports all tests passing, and `git diff --check` exits 0.

- [ ] **Step 2: Verify removed implementation and configuration references**

Run:

```bash
rg -n "VISION_MODEL_MODE|VISION_MODEL_SEARCH_INPUT|VISION_MODEL_ENABLE_SEARCH|VISION_MODEL_SEARCH_TIMEOUT_SECONDS|image_search|web_search" qq_rolebot tests README.md docs .env.example
```

Expected: no runtime or current-documentation references. Historical design/plan files may still mention the old implementation and do not need rewriting.

- [ ] **Step 3: Inspect repository hygiene**

Run:

```bash
git status --short --untracked-files=all
rg -n "SERPAPI_API_KEY=.+[^.]|R2_SECRET_ACCESS_KEY=.+[^.]|api_key\s*=\s*['\"][^'\"]+" .env.example README.md docs tests qq_rolebot scripts
```

Expected: only intentional source/test/doc changes appear, and no real-looking credentials or signed URLs are present. Review matches manually because test placeholders are allowed.

- [ ] **Step 4: Document but do not automate the production probe**

With secrets present only in the server `.env`, run a manual diagnostic against the approved non-private evaluation set. Record:

```text
image_hash, category, expected_identity, pipeline_result, confidence_band,
wrong_confirmation, conservative_rejection, duration_ms, lens_used, web_used
```

Acceptance gate before enabling production:

- zero wrong confirmations in the initial evaluation set;
- P95 vision duration at or below the configured budget;
- no temporary R2 object remains beyond lifecycle expectations;
- traces contain no image bytes, signed URLs, QQ query strings, or credentials.

Do not place the evaluation images or production responses in Git.

- [ ] **Step 5: Commit any final task-related fixes**

If verification required changes:

```bash
git add <only-task-related-files>
git commit -m "fix: finalize evidence vision pipeline"
```

If no changes were required, do not create an empty commit.
