# Lens-First Vision Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Implementation note:** Execute tasks in order. Each task uses focused failing tests before implementation and ends with an isolated commit. Do not deploy or push `master` unless the user explicitly requests it.

**Goal:** Replace the current dual-Lens, deterministic-resolver, R2-required vision path with a Lens `type=all` first pipeline followed by one multi-image Qwen synthesis call and bounded optional exact/Web fallbacks.

**Architecture:** Reuse bounded image preprocessing, SQLite cache infrastructure, service trigger boundaries, and trace redaction. Rewrite the SerpApi client around asynchronous `type=all` searches, replace the current visual/candidate-extraction calls with one multi-image synthesis schema, and simplify `VisionPipeline` so code controls deadlines and caching while Qwen performs lightweight semantic judgment. The normal path must never call `exact_matches`; exact and Web searches are conditional fallbacks requested by the first Qwen result. Remove R2 as a runtime requirement; an optional HTTPS publisher remains a future backend and is not required in this implementation cycle.

**Tech Stack:** Python 3.11, asyncio, httpx, Pillow, aiosqlite, NoneBot2, OneBot v11, pytest, pytest-asyncio, Ruff.

**Design:** `docs/superpowers/specs/2026-07-12-lens-first-vision-pipeline-design.md`

## File Structure

### Keep And Refactor

- `qq_rolebot/image_preprocessor.py`: add bounded model-input resizing while preserving normalized hashing.
- `qq_rolebot/serpapi_client.py`: implement async Lens `type=all`, conditional exact, and bounded Web Search.
- `qq_rolebot/vision_client.py`: replace pre-Lens visual analysis and post-Lens candidate extraction with one multi-image synthesis call and one text-only re-evaluation call.
- `qq_rolebot/vision_cache.py`: store per-image Lens stages and combined Qwen synthesis results.
- `qq_rolebot/vision_pipeline.py`: orchestrate deduplication, bounded Lens concurrency, one Qwen call, conditional fallback, and absolute deadlines.
- `qq_rolebot/config.py`: expose only operationally useful Lens-first settings and remove R2 requirements.
- `qq_rolebot/plugins/roleplay_chat.py`: wire optional Lens availability without requiring R2.
- `qq_rolebot/service.py`: preserve the service-facing protocol and adapt context formatting only where required.
- `scripts/summarize_vision_traces.py`: aggregate the new stage names and fallback metrics.

### Add

- `scripts/probe_vision_pipeline.py`: manual, sanitized production probe for Lens `all` and Qwen synthesis.
- `scripts/evaluate_vision_pipeline.py`: run a server-local labeled JSONL set and report accuracy, false confirmations, fallback rates, and latency percentiles without storing images or provider responses.
- `tests/fixtures/serpapi/google_lens_all_processing.json`: sanitized async submission fixture.
- `tests/fixtures/serpapi/google_lens_all_success.json`: sanitized `type=all` success fixture.
- `tests/fixtures/serpapi/google_lens_exact_success.json`: sanitized conditional exact fixture.

### Remove

- `qq_rolebot/vision_resolver.py`: deterministic identity resolver is no longer in the selected design.
- `tests/test_vision_resolver.py`: superseded by structured Qwen synthesis and pipeline fallback tests.
- `qq_rolebot/temp_image_store.py`: R2 is not part of the first Lens-first implementation.
- `tests/test_temp_image_store.py`: superseded by tests proving the pipeline works with no publisher.
- `boto3` from `pyproject.toml` when no other repository code imports it.

## Task 1: Define Lens-First Shared Types

**Files:**

- Modify: `qq_rolebot/vision_types.py`
- Modify: `tests/test_vision_types.py`

- [ ] **Step 1: Write failing type and context-format tests**

Add tests for these immutable records:

```python
LensAllEvidence(
    visual_matches=(),
    related_content=(),
    ai_overview="",
)

LensSearchResult(
    ok=True,
    evidence=LensAllEvidence(
        visual_matches=(),
        related_content=(),
        ai_overview="synthetic overview",
    ),
    error="",
    unreachable=False,
    cached=False,
)

ImageLensResult(
    image_number=1,
    search=LensSearchResult(
        ok=True,
        evidence=LensAllEvidence(ai_overview="synthetic overview"),
    ),
)

ImageDecision(
    image_number=1,
    confidence=ConfidenceBand.CONFIRMED,
    scene_description="synthetic scene",
    visible_text=("synthetic text",),
    subject_identity="Priestess",
    work_or_affiliation="Arknights",
    source_series_or_author="Arknights",
    reason="the image and Lens summary agree",
    needs_exact=False,
    needs_web=False,
    verification_query="",
)

VisionSynthesis(
    images=(
        ImageDecision(
            image_number=1,
            confidence=ConfidenceBand.NO_IDENTITY,
            scene_description="synthetic landscape",
        ),
    ),
    combined_answer="one synthetic landscape",
)

ExactSearchResult(
    ok=True,
    sources=(),
    error="",
    cached=False,
)

ImageFallbackEvidence(
    image_number=1,
    exact_sources=(),
    web_sources=(),
    exact_error="",
    web_error="",
)
```

Test that context text:

- labels every image in order;
- preserves source/series separately from subject identity;
- marks uncertain results explicitly without adding strict evidence-threshold language;
- includes a bounded multi-image conclusion when present;
- never prints provider errors or URLs.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py
```

Expected: failure because the new records and formatting do not exist.

- [ ] **Step 3: Implement the shared records**

Extend the existing `ConfidenceBand` enum with `no_identity`; keep `confirmed`, `uncertain`, and `unavailable`. Add `LensAllEvidence`, `LensSearchResult`, `ImageLensResult`, `ImageDecision`, `VisionSynthesis`, `ExactSearchResult`, and `ImageFallbackEvidence`. Keep the existing resolver-oriented records temporarily so the repository remains green until the pipeline switches in Task 7. Keep `SearchSource` as the normalized search-result record.

Keep serialization-friendly dataclasses with tuples rather than mutable lists.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_types.py tests/test_vision_types.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_types.py tests/test_vision_types.py
git commit -m "refactor: define lens-first vision types"
```

## Task 2: Replace Vision Configuration And Remove R2 Dependency

**Files:**

- Modify: `qq_rolebot/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Update default and override tests for:

```text
VISION_MODEL_TIMEOUT_SECONDS=20
VISION_MODEL_ENABLE_THINKING=false
VISION_PIPELINE_TIMEOUT_SECONDS=50
VISION_PIPELINE_MULTI_TIMEOUT_SECONDS=70
VISION_PIPELINE_MAX_IMAGES=4
VISION_PIPELINE_MODEL_MAX_EDGE=1600
SERPAPI_LENS_TIMEOUT_SECONDS=35
SERPAPI_POLL_INTERVAL_SECONDS=0.75
SERPAPI_LENS_CONCURRENCY=2
SERPAPI_EXACT_FALLBACK_ENABLED=true
SERPAPI_WEB_FALLBACK_ENABLED=true
SERPAPI_MAX_EXACT_FALLBACKS_PER_MESSAGE=2
SERPAPI_MAX_WEB_FALLBACKS_PER_MESSAGE=2
VISION_TEMP_PUBLISHER_ENABLED=false
```

Add validation tests for:

- nonpositive timeouts, max edge, image count, concurrency, and polling interval;
- negative fallback limits;
- multi-image timeout less than the single-image timeout;
- `VISION_TEMP_PUBLISHER_ENABLED=true` being rejected with a clear unsupported-backend message in this implementation cycle, rather than silently pretending HTTPS publication exists.

Mark these settings as deprecated but retain their existing parsing until Task 8, so the current plugin remains importable between commits:

- `VISION_TEMP_STORE_BACKEND`;
- `R2_ACCOUNT_ID`;
- `R2_ACCESS_KEY_ID`;
- `R2_SECRET_ACCESS_KEY`;
- `R2_BUCKET`;
- `R2_PRESIGNED_URL_SECONDS`;
- `R2_OBJECT_PREFIX`.

- [ ] **Step 2: Run configuration tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_config.py
```

- [ ] **Step 3: Implement settings migration**

Add the Lens-first fields to `Settings` and `load_settings`. Keep deprecated R2 fields unchanged in this task; Task 8 removes them only after plugin wiring no longer constructs the old store.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_config.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/config.py tests/test_config.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/config.py tests/test_config.py
git commit -m "refactor: configure lens-first vision"
```

## Task 3: Bound Qwen Image Inputs

**Files:**

- Modify: `qq_rolebot/image_preprocessor.py`
- Modify: `tests/test_image_preprocessor.py`

- [ ] **Step 1: Write failing preprocessing tests**

Add tests proving:

- images with a long edge above 1600 are resized while preserving aspect ratio;
- smaller images are not enlarged;
- EXIF orientation is applied before resizing;
- four normalized images cannot accidentally retain their original multi-megabyte PNG payloads when JPEG is suitable;
- normalized SHA-256 is deterministic for identical decoded inputs;
- animated media remains outside the static-image path.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_image_preprocessor.py
```

- [ ] **Step 3: Implement model-edge resizing**

Add `model_max_edge=1600` as a backward-compatible constructor default in `ImagePreprocessor`. Resize with Pillow's high-quality downsampling before encoding. Prefer JPEG for opaque RGB photographic or illustration content and PNG only when alpha must be preserved. Do not add a second download or a second decode. Task 7 passes the configured value explicitly.

The hash remains based on the normalized model-ready bytes, so temporary QQ URL changes reuse the same cache entry.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_image_preprocessor.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/image_preprocessor.py tests/test_image_preprocessor.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/image_preprocessor.py tests/test_image_preprocessor.py
git commit -m "feat: bound vision model image inputs"
```

## Task 4: Rewrite SerpApi Around Async Lens `type=all`

**Files:**

- Modify: `qq_rolebot/serpapi_client.py`
- Modify: `tests/test_serpapi_client.py`
- Add: `tests/fixtures/serpapi/google_lens_all_processing.json`
- Add: `tests/fixtures/serpapi/google_lens_all_success.json`
- Add: `tests/fixtures/serpapi/google_lens_exact_success.json`

- [ ] **Step 1: Add sanitized fixtures and failing client tests**

Cover:

- initial `type=all&async=true` submission returns `Processing` and a search ID;
- polling `/searches/{id}.json` transitions to `Success`;
- request omits `no_cache` entirely and defaults `auto_crop` off;
- cached success returns without polling;
- `Error`, missing search ID, malformed JSON, HTTP failure, and deadline exhaustion;
- `visual_matches`, `related_content`, and bounded `ai_overview` parsing;
- conditional `search_exact(image_url)`;
- bounded `search_web(query)` without candidate-specific resolver semantics;
- 0.75-second polling through an injected sleep function so tests do not actually sleep;
- API key and complete image URL never appear in traces;
- a successful stage remains usable even when a later conditional stage fails.

The fixture must contain only synthetic URLs and titles. Do not copy raw production responses.

- [ ] **Step 2: Run SerpApi tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_serpapi_client.py
```

- [ ] **Step 3: Implement async clients**

Refactor `SerpApiLensClient` to expose:

```python
async def search_all(image_url, *, timeout_seconds, trace=None) -> LensSearchResult
async def search_exact(image_url, *, timeout_seconds, trace=None) -> ExactSearchResult
async def close() -> None
```

Use one reusable `httpx.AsyncClient` per runtime client. Submit asynchronously, poll with an absolute deadline, and record status transitions without storing the search ID in user-facing context.

Refactor `SerpApiWebClient` to add a bounded `search(query)` method. Retain `SerpApiLensClient.search()` and `SerpApiWebClient.verify()` for the current pipeline until Task 7 switches all call sites, then remove both compatibility methods in Task 8. Add a test asserting `search_exact()` is not called by `search_all()`.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_serpapi_client.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/serpapi_client.py tests/test_serpapi_client.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/serpapi_client.py tests/test_serpapi_client.py tests/fixtures/serpapi
git commit -m "feat: add async lens all search"
```

## Task 5: Replace Visual Analysis With One Multi-Image Qwen Synthesis

**Files:**

- Modify: `qq_rolebot/vision_client.py`
- Modify: `tests/test_vision_client.py`

- [ ] **Step 1: Write failing synthesis tests**

Add tests for these new APIs while retaining the existing `analyze_image` and `extract_search_candidates` tests until Task 7 switches the pipeline:

```python
async def synthesize(
    images: tuple[NormalizedImage, ...],
    lens_results: tuple[ImageLensResult, ...],
    *,
    user_question: str,
    chat_context: str,
    timeout_seconds: float,
    trace=None,
) -> VisionSynthesis

async def reevaluate(
    previous: VisionSynthesis,
    fallback_results: tuple[ImageFallbackEvidence, ...],
    *,
    timeout_seconds: float,
    trace=None,
) -> VisionSynthesis
```

Test that the main payload:

- sets `enable_thinking=false`;
- contains all images once and in message order;
- labels Lens evidence by image number;
- marks Lens failures without omitting the image;
- includes user question and bounded chat context;
- requests subject identity, work, source/author, confidence, reason, fallback booleans, verification query, and combined multi-image answer;
- accepts a meme source without requiring a canonical person name;
- parses confirmed, uncertain, and no-identity records;
- redacts Base64, API key, search snippets beyond bounds, and QQ URL data.

Test that `reevaluate` is text-only and cannot re-upload images.

Keep focused tests for `describe_dynamic_media` with thinking disabled.

- [ ] **Step 2: Run Qwen client tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_client.py
```

- [ ] **Step 3: Implement synthesis and re-evaluation**

Keep schema-constrained JSON output. Bound per-image Lens text and total multi-image prompt size. Qwen makes lightweight semantic judgments; do not recreate `VisionEvidenceResolver` inside the client. Keep legacy methods temporarily and remove them in Task 8 after all production call sites are gone.

Return an unavailable or uncertain synthesis on malformed JSON without exposing provider errors to the final context.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_client.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_client.py tests/test_vision_client.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_client.py tests/test_vision_client.py
git commit -m "refactor: synthesize lens and image context"
```

## Task 6: Adapt Cache For Lens Stages And Combined Questions

**Files:**

- Modify: `qq_rolebot/vision_cache.py`
- Modify: `tests/test_vision_cache.py`

- [ ] **Step 1: Write failing cache tests**

Cover:

- per-image `lens_all` round trip;
- per-image conditional exact round trip;
- combined Qwen synthesis keyed by ordered image hashes;
- different image order does not collide;
- different normalized user question does not collide;
- different bounded chat-context digest does not collide;
- model, prompt, parser, and schema version changes invalidate combined results;
- no image bytes, Base64, complete QQ URL, API key, or full raw response is persisted;
- corrupt payload and expired entries remain cache misses.

- [ ] **Step 2: Run cache tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_cache.py
```

- [ ] **Step 3: Implement stage-specific methods**

Reuse the existing SQLite table; stage names and request hashes do not require a schema migration. Add a helper that hashes:

```text
ordered image hashes
normalized question
bounded chat-context digest
model name
prompt version
Lens parser version
schema version
```

Add new methods without removing observation/resolution methods yet. Task 8 removes legacy cache methods after the plugin and pipeline switch.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_cache.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_cache.py tests/test_vision_cache.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_cache.py tests/test_vision_cache.py
git commit -m "refactor: cache lens-first vision stages"
```

## Task 7: Switch Pipeline And Runtime Wiring

**Files:**

- Modify: `qq_rolebot/vision_pipeline.py`
- Modify: `tests/test_vision_pipeline.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Modify: `tests/test_plugin_smoke.py`
- Modify: `qq_rolebot/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Replace orchestration tests with failing Lens-first cases**

Use fakes with controllable clocks and delays. Cover:

1. One image: preprocess, Lens `all`, one synthesis, no fallback.
2. Lens unavailable: one direct Qwen synthesis with an empty Lens result.
3. `needs_exact`: one exact request and one text-only re-evaluation.
4. `needs_web`: one bounded Web Search and one text-only re-evaluation.
5. Both fallbacks requested: run them concurrently when budget permits.
6. No more than one re-evaluation.
7. Per-message exact and Web limits of two.
8. Lens deadline at 35 seconds leaves Qwen time inside the 50-second message deadline.
9. Three or four images stop Lens at 50 seconds and reserve 20 seconds for Qwen.
10. Up to four images remain in order.
11. Lens concurrency never exceeds two.
12. Duplicate images search once and map the result back to every original position.
13. One image failure does not remove other image results.
14. Complete combined-cache hit skips providers.
15. Per-image Lens cache hit still runs Qwen for a new question.
16. Same-hash concurrent requests share one in-flight Lens task.
17. Cancellation removes in-flight task entries without poisoning later requests.
18. Dynamic media remains isolated from static Lens calls.
19. `close()` closes reusable HTTP clients and waits for no abandoned tasks.
20. Lens receives the original QQ source URL while Qwen receives only normalized image bytes.
21. A normal multi-image result with every `needs_exact=false` makes zero `search_exact()` calls.
22. Exact and Web fallback evidence maps back only to the requesting image number.
23. A fifth static image keeps an ordinary overflow marker but makes no Lens or Qwen image input.

Add integration tests proving:

24. Qwen settings are required when vision is enabled.
25. A SerpApi key enables Lens; a missing key or disabled Lens degrades to Qwen-only instead of disabling vision.
26. `SERPAPI_SEARCH_ENABLED=false` disables only Web fallback, not Lens `all`.
27. Runtime wiring passes single/multi deadlines, max four images, model max edge, polling interval, and concurrency.
28. Startup and shutdown initialize cache and close pipeline clients.
29. Existing private, group whitelist, direct-address, and follow-up trigger behavior is unchanged.
30. An untriggered group image makes no image download, Lens, or Qwen call.
31. User question and bounded chat context reach the Lens-first pipeline.
32. Four image markers remain ordered in Vision Context.
33. Uncertain Qwen output remains uncertain in the main-model prompt.
34. Lens/Qwen failure keeps text fallback.
35. Follow-up and replied-image context remain conversation-scoped.

Remove R2 and deterministic resolver expectations from the switched pipeline and wiring tests. Keep the now-dead legacy modules and compatibility methods on disk until Task 8 so this commit can switch all call sites before cleanup.

- [ ] **Step 2: Run pipeline tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_pipeline.py tests/test_plugin_smoke.py tests/test_service.py
```

- [ ] **Step 3: Implement absolute-deadline orchestration**

Suggested internal phases:

```text
prepare selected images
deduplicate by normalized hash
load per-image Lens cache
run missing Lens all tasks under semaphore(2)
cut Lens stage at single/multi stage deadline
load or run one combined Qwen synthesis
run bounded requested fallbacks if remaining budget permits
run at most one text-only re-evaluation
store stage and combined caches
format best available context at hard deadline
```

Use one message-level deadline and compute remaining time before every external call. Do not use additive component timeouts.

Implement in-flight Lens coalescing with an `asyncio.Lock` and a hash-to-task map owned by `VisionPipeline`.

Update plugin wiring in the same task:

```python
vision_ready = all((
    settings.vision_model_api_base,
    settings.vision_model_api_key,
    settings.vision_model_name,
))
lens_client = (
    SerpApiLensClient(
        api_key=settings.serpapi_api_key,
        timeout_seconds=settings.serpapi_lens_timeout_seconds,
        poll_interval_seconds=settings.serpapi_poll_interval_seconds,
    )
    if settings.serpapi_lens_enabled and settings.serpapi_api_key
    else None
)
web_client = (
    SerpApiWebClient(
        api_key=settings.serpapi_api_key,
        timeout_seconds=settings.serpapi_lens_timeout_seconds,
    )
    if settings.serpapi_web_fallback_enabled
    and settings.serpapi_search_enabled
    and settings.serpapi_api_key
    else None
)
```

Construct `VisionPipeline` with no resolver or temporary-store argument. Pass the configured question and bounded conversation context through the existing service vision protocol; do not move provider-specific behavior into `ChatService`.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_pipeline.py tests/test_plugin_smoke.py tests/test_service.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/vision_pipeline.py qq_rolebot/plugins/roleplay_chat.py qq_rolebot/service.py tests/test_vision_pipeline.py tests/test_plugin_smoke.py tests/test_service.py
```

Confirm production call sites no longer import or construct legacy components:

```bash
rg -n "VisionEvidenceResolver|R2TemporaryImageStore|vision_resolver|temp_image_store" qq_rolebot/plugins qq_rolebot/service.py qq_rolebot/vision_pipeline.py tests/test_plugin_smoke.py tests/test_service.py tests/test_vision_pipeline.py
```

Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/vision_pipeline.py qq_rolebot/plugins/roleplay_chat.py qq_rolebot/service.py tests/test_vision_pipeline.py tests/test_plugin_smoke.py tests/test_service.py
git commit -m "feat: switch to lens-first vision pipeline"
```

## Task 8: Remove Legacy Resolver And R2 Runtime

**Files:**

- Delete: `qq_rolebot/vision_resolver.py`
- Delete: `tests/test_vision_resolver.py`
- Delete: `qq_rolebot/temp_image_store.py`
- Delete: `tests/test_temp_image_store.py`
- Delete: `tests/fixtures/serpapi/google_lens.json`
- Modify: `qq_rolebot/vision_types.py`
- Modify: `tests/test_vision_types.py`
- Modify: `qq_rolebot/serpapi_client.py`
- Modify: `tests/test_serpapi_client.py`
- Modify: `qq_rolebot/vision_client.py`
- Modify: `tests/test_vision_client.py`
- Modify: `qq_rolebot/vision_cache.py`
- Modify: `tests/test_vision_cache.py`
- Modify: `qq_rolebot/config.py`
- Modify: `tests/test_config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Tighten tests around the post-migration surface**

Update focused tests so:

- resolver-only records and serialization helpers are no longer public or imported;
- old dual-Lens `search()`, candidate-specific `verify()`, `analyze_image()`, and `extract_search_candidates()` methods no longer exist;
- observation/resolution cache methods no longer exist;
- old R2 environment variables are ignored rather than required or copied into `Settings`;
- `VISION_TEMP_PUBLISHER_ENABLED=false` remains valid and `true` still raises the explicit unsupported-backend error;
- importing plugin, service, and pipeline modules succeeds after the legacy files are deleted;
- no remaining project import requires `boto3`.

- [ ] **Step 2: Run cleanup tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py tests/test_serpapi_client.py tests/test_vision_client.py tests/test_vision_cache.py tests/test_config.py tests/test_plugin_smoke.py
```

- [ ] **Step 3: Delete compatibility code and dependency**

Delete the resolver and R2 store modules and their dedicated tests. Remove only legacy records and methods that have no call sites after Task 7. Remove deprecated R2 fields from `Settings` and `load_settings`; tolerate unknown old environment variables through the existing environment-loading behavior. Remove `boto3` from `pyproject.toml` after `rg -n "boto3|botocore" qq_rolebot scripts tests` returns no runtime use.

- [ ] **Step 4: Run focused and import validation**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_vision_types.py tests/test_serpapi_client.py tests/test_vision_client.py tests/test_vision_cache.py tests/test_config.py tests/test_plugin_smoke.py tests/test_service.py tests/test_vision_pipeline.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot tests
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -c "import qq_rolebot.plugins.roleplay_chat, qq_rolebot.service, qq_rolebot.vision_pipeline"
rg -n "VisionEvidenceResolver|R2TemporaryImageStore|vision_resolver|temp_image_store|boto3|botocore" qq_rolebot tests scripts pyproject.toml
```

Expected: tests and imports pass; the final `rg` has no matches.

- [ ] **Step 5: Commit**

```bash
git rm qq_rolebot/vision_resolver.py tests/test_vision_resolver.py qq_rolebot/temp_image_store.py tests/test_temp_image_store.py tests/fixtures/serpapi/google_lens.json
git add qq_rolebot/vision_types.py tests/test_vision_types.py qq_rolebot/serpapi_client.py tests/test_serpapi_client.py qq_rolebot/vision_client.py tests/test_vision_client.py qq_rolebot/vision_cache.py tests/test_vision_cache.py qq_rolebot/config.py tests/test_config.py pyproject.toml
git commit -m "refactor: remove legacy vision runtime"
```

## Task 9: Add Observability, Probe, Evaluation, And Docs

**Files:**

- Modify: `scripts/summarize_vision_traces.py`
- Modify: `tests/test_summarize_vision_traces.py`
- Add: `scripts/probe_vision_pipeline.py`
- Add: `tests/test_probe_vision_pipeline.py`
- Add: `scripts/evaluate_vision_pipeline.py`
- Add: `tests/test_evaluate_vision_pipeline.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Write failing trace and probe tests**

Trace summary tests should aggregate:

- `vision.lens_all.submit` and final status;
- Lens all duration and cache state;
- Qwen synthesis and re-evaluation duration;
- exact and Web fallback counts;
- per-image failures;
- single/combined cache hits;
- in-flight coalescing count;
- total duration and hard timeout rate.

Probe tests should verify that the script:

- reads provider keys only from environment or `.env`;
- accepts a public test image URL without persisting it;
- prints status, duration, result counts, and sanitized identity fields;
- never prints API keys, Authorization headers, Base64, complete QQ query strings, or raw provider responses;
- supports `--lens-only` and `--full` modes;
- exits nonzero on DNS, TLS, authentication, timeout, and malformed-response failures.

Evaluation tests should use a synthetic JSONL manifest such as:

```json
{"id":"case-01","image_url":"https://example.invalid/case-01.jpg","question":"图中是谁？","expected_any":["Priestess"],"expected_confidence":"confirmed"}
```

Verify that the evaluator:

- accepts 20–50 server-local cases without copying images into Git;
- records correct identification, wrong confirmation, uncertain, no-identity, and provider-failure counts;
- reports P50/P90/P95 total latency plus main-path, exact-fallback, and Web-fallback rates;
- reports SerpApi query consumption per cold image and cache-hit latency separately;
- prints only case IDs and aggregate labels, never complete image URLs or raw model/search responses;
- supports a dry-run manifest validation mode that consumes no provider quota;
- exits nonzero when the manifest contains private-image paths, duplicate IDs, invalid labels, or fewer than 20 cases for a formal run.

- [ ] **Step 2: Run script tests and verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_summarize_vision_traces.py tests/test_probe_vision_pipeline.py tests/test_evaluate_vision_pipeline.py
```

- [ ] **Step 3: Implement observability and documentation**

Update examples and runbook for:

- Lens `type=all` first;
- 25-second soft target, 50-second single/two-image hard timeout, and 70-second multi-image timeout;
- maximum four images and Lens concurrency two;
- conditional exact/Web fallback;
- thinking disabled;
- optional Lens when SerpApi key is missing;
- no R2 requirement;
- temporary HTTPS publisher explicitly deferred and disabled;
- manual probe commands that never echo secrets;
- a server-local 20–50 image evaluation manifest format and command;
- SerpApi free-plan query consumption and hash-cache behavior.

Remove R2 setup instructions and obsolete deterministic evidence claims from current docs.

- [ ] **Step 4: Run focused validation**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_summarize_vision_traces.py tests/test_probe_vision_pipeline.py tests/test_evaluate_vision_pipeline.py tests/test_config.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check scripts/summarize_vision_traces.py scripts/probe_vision_pipeline.py scripts/evaluate_vision_pipeline.py tests/test_summarize_vision_traces.py tests/test_probe_vision_pipeline.py tests/test_evaluate_vision_pipeline.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add scripts/summarize_vision_traces.py scripts/probe_vision_pipeline.py scripts/evaluate_vision_pipeline.py tests/test_summarize_vision_traces.py tests/test_probe_vision_pipeline.py tests/test_evaluate_vision_pipeline.py .env.example README.md docs/deployment.md
git commit -m "docs: document lens-first vision operations"
```

## Task 10: Full Verification And Production Probe

**Files:**

- Modify only if verification exposes task-related defects.

- [ ] **Step 1: Run the complete local suite**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

- [ ] **Step 2: Verify obsolete paths are gone**

```bash
rg -n "R2TemporaryImageStore|VisionEvidenceResolver|VISION_TEMP_STORE_BACKEND|R2_ACCOUNT_ID|R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|R2_BUCKET|SERPAPI_TIMEOUT_SECONDS=8|VISION_PIPELINE_TIMEOUT_SECONDS=15" qq_rolebot tests scripts .env.example README.md docs pyproject.toml
```

Expected: only historical design/plan documents may contain old names. Runtime code and current user/deployment docs must not.

- [ ] **Step 3: Inspect repository hygiene**

```bash
git status --short --untracked-files=all
git diff --check
rg -n "SERPAPI_API_KEY=.+[^.]|VISION_MODEL_API_KEY=.+[^.]|api_key\s*=\s*['\"][^'\"]+" .env.example README.md docs tests qq_rolebot scripts
find . -maxdepth 3 -type f \( -name '*.db' -o -name '*.sqlite3' -o -name '*.png' -o -name '*.jpg' -o -name '*.webp' \) -print
```

Review every match. Do not commit real keys, QQ images, temporary URLs, trace files, caches, or databases.

- [ ] **Step 4: Run the sanitized production probe**

Only after the user confirms server testing is desired and production `.env` contains the required keys:

```bash
cd /opt/qq-rolebot
/opt/miniconda3/envs/qq-rolebot/bin/python scripts/probe_vision_pipeline.py --lens-only
/opt/miniconda3/envs/qq-rolebot/bin/python scripts/probe_vision_pipeline.py --full
```

Verify:

- Lens reaches a terminal status;
- Qwen returns valid structured output;
- logs contain no key, Base64, or reusable image URL;
- one repeated probe uses SerpApi or application cache;
- no temporary image remains after the probe.

After the probe passes, validate and run the server-local non-private evaluation manifest:

```bash
/opt/miniconda3/envs/qq-rolebot/bin/python scripts/evaluate_vision_pipeline.py --manifest /opt/qq-rolebot/data/vision-eval/cases.jsonl --dry-run
/opt/miniconda3/envs/qq-rolebot/bin/python scripts/evaluate_vision_pipeline.py --manifest /opt/qq-rolebot/data/vision-eval/cases.jsonl
```

Record aggregate accuracy, wrong confirmations, uncertain rate, P50/P90/P95, exact/Web fallback rates, and cold/cache query consumption. Do not copy the manifest, images, or raw outputs back into Git.

Do not enable production vision, restart services, push `master`, or deploy unless the user explicitly requests it.

- [ ] **Step 5: Commit verification fixes if needed**

If verification required code or documentation fixes, stage only the exact files shown by `git diff --name-only` that belong to this feature, then commit them with `git commit -m "fix: finalize lens-first vision pipeline"`.

If no fixes were needed, do not create an empty commit.

## Implementation Checkpoints

Pause for review after:

1. Task 4, when live request semantics and fixtures are stable.
2. Task 7, when the new orchestration and runtime wiring have switched off R2/resolver paths.
3. Task 9, before any production probe or deployment work.

At each checkpoint, summarize changed files, focused test results, remaining risks, and any deviation from the approved design.
