# Evidence-Driven Vision Pipeline Design

## Goal

Replace the current vision implementation with an evidence-driven image understanding pipeline that
prioritizes accuracy while keeping the vision stage within a configurable total time budget.

The pipeline must:

- Understand arbitrary image questions without routing users into predefined task categories.
- Describe visible content and text even when an identity cannot be established.
- Provide additional identity and work information when a public person, fictional character, or
  anime-style character can be identified reliably.
- Prefer refusing to identify over giving a plausible but weakly supported identity.
- Combine visual analysis, reverse-image search, and web search instead of relying on Qwen's opaque
  built-in search-tool behavior.
- Finish the vision stage within `VISION_PIPELINE_TIMEOUT_SECONDS`, defaulting to 15 seconds. This
  budget does not include the existing main conversation-model call.
- Preserve the existing trigger policy: media is processed only after the bot has already decided it
  may reply.

## Current Problems

The current `VisionClient` mixes image download, visual description, Qwen Responses API image
search, web search, result summarization, timeout handling, and trace logging in one class.

The default hybrid path is both slow and difficult to validate:

1. QQ images are downloaded and converted to data URLs.
2. A visual chat-completions request runs with thinking enabled by default.
3. An image-search and web-search Responses API request runs afterward.
4. The main conversation model runs only after both vision calls finish.

These expensive operations are mostly serial. Their independent timeouts can accumulate rather
than respecting one end-to-end vision deadline.

Accuracy is also limited:

- The visual model receives a fixed instruction but not the user's concrete question and useful chat
  context.
- General scene description, identity guessing, reverse-image search, and web research are collapsed
  into free-form text.
- The code declares `image_search` and `web_search` tools but does not verify tool-call records or
  tool usage metadata. A successful final text response therefore does not prove either tool ran.
- Tests accept mocked final text without any mocked tool-call records.
- The default reverse-search input is a data URL, while externally hosted image URLs are the normal
  input for reverse-image engines.
- Search output is unconditionally presented as higher priority than the visual description, even
  when it is weak, conflicting, or unrelated.
- The output has no structured candidates, sources, confidence evidence, or deterministic identity
  threshold.

## Selected Approach

Use a dedicated evidence pipeline:

1. Preprocess and fingerprint each image once.
2. Run structured visual analysis and temporary-image publication concurrently.
3. Run Google Lens through SerpApi against a short-lived public image URL.
4. Extract and normalize candidate entities deterministically.
5. Use SerpApi Google Search to verify only the strongest one or two candidates.
6. Resolve identity through deterministic evidence thresholds, using a small model only to extract
   structured observations or compress already selected evidence.
7. Return a concise vision context to the existing main conversation model.

The current Qwen Responses API `image_search` and `web_search` path will be removed. The visual model
will not perform hidden search.

## Non-Goals

- Do not make the model decide whether the bot may respond.
- Do not classify every user request into a fixed product-level image-task pipeline.
- Do not guarantee identification of every person, character, meme, location, or object.
- Do not identify private individuals from facial similarity or social-profile search results.
- Do not retain user images in the repository or permanent application storage.
- Do not log image bytes, Base64 data, signed object URLs, API keys, or unredacted QQ temporary URLs.
- Do not run both the old and new vision implementations in production.
- Do not include the main roleplay-model generation time in the vision budget.

## Architecture

### `ImagePreprocessor`

Responsibilities:

- Download an allowed QQ HTTP(S) image once with redirect and size limits.
- Validate the detected image format instead of trusting only the response header.
- Decode the image safely and enforce pixel-count limits.
- Correct EXIF orientation.
- Resize or transcode when required by model or search limits.
- Compute SHA-256 from the normalized image bytes.
- Produce one normalized in-memory image artifact shared by visual analysis and temporary storage.

The preprocessor must reject unsupported content, decompression bombs, oversized downloads, and
invalid image payloads without persisting the content.

### `VisualAnalyzer`

Responsibilities:

- Receive one normalized image, the user's original question, and a bounded amount of relevant chat
  context.
- Call a multimodal model without built-in search tools.
- Request structured output containing:
  - objective scene description;
  - visible text and uncertain OCR fragments;
  - detected people or fictional/anime-style characters;
  - distinctive visual features;
  - cautious identity candidates;
  - a visual reason for each candidate;
  - explicit uncertainty.
- Avoid turning visual resemblance alone into a confirmed identity.

The visual-model timeout is a component cap. The shared pipeline deadline remains authoritative.
Thinking is disabled by default so that the time budget can be spent on independently verifiable
search evidence. It remains configurable for model-specific evaluation.

### `TemporaryImageStore`

Define a provider-neutral interface that can:

- upload normalized image bytes under an unpredictable object key;
- create a short-lived HTTPS GET URL;
- delete the object idempotently.

The initial implementation is `R2TemporaryImageStore`, backed by Cloudflare R2 through its
S3-compatible API.

Operational rules:

- Use a dedicated private bucket or private prefix.
- Default signed-URL lifetime: 300 seconds.
- Delete the object in a `finally` cleanup path after search completes.
- Configure an R2 lifecycle rule to remove `vision-temp/` objects after one day as a crash-recovery
  fallback.
- Never record the signed URL in traces.
- Cleanup is best effort and does not extend the user's synchronous wait path.

### `ReverseImageSearcher`

The initial implementation uses SerpApi Google Lens.

Responsibilities:

- Submit one public image URL per Lens request.
- Parse exact matches, visual matches, image-background information when present, titles, source
  domains, and result page URLs.
- Preserve which image produced each result.
- Normalize and truncate the response before it reaches any model.
- Return explicit status when Lens could not fetch the image.

The searcher first tries the original QQ URL. R2 publication runs concurrently and provides a
reliable fallback. If the original-URL Lens request fails because the image is
unreachable, the pipeline retries once with the R2 signed URL when sufficient deadline remains.
It must not run both full Lens searches unnecessarily after one has produced usable results.

### `WebEvidenceSearcher`

The initial implementation uses SerpApi Google Search.

Responsibilities:

- Accept only concrete candidate entities produced by visual analysis or Lens normalization.
- Verify relationships such as person-to-image context, character-to-work, work-to-scene, or named
  source-to-result page.
- Search only the strongest one or two candidates.
- Run candidate queries concurrently within the shared remaining deadline.
- Return supporting and contradicting sources separately.

The component must not start broad, unbounded browsing when no concrete candidate exists.

### `VisionEvidenceResolver`

Responsibilities:

- Merge structured visual observations, Lens evidence, and web evidence.
- Apply deterministic eligibility rules for identity confirmation.
- Reject candidates with conflicting or insufficient evidence.
- Produce a structured `VisionResolution` and a concise context string for the roleplay model.

A language model may be used for schema-constrained extraction and concise phrasing, but it cannot
bypass deterministic confirmation rules.

### `VisionPipeline`

Responsibilities:

- Enforce one absolute vision deadline.
- Coordinate preprocessing, caching, concurrent calls, cancellation, retries, and cleanup.
- Process each image independently so evidence cannot leak between images.
- Limit the number of processed images per message.
- Produce trace events and stage metrics.
- Return the best completed reliable evidence at deadline instead of waiting for every component.

`ChatService` will call this single interface and will not know SerpApi, R2, or model-specific API
details.

## Data Model

The implementation should use typed records equivalent to the following conceptual structure:

```text
VisionEvidence
├── image_id
├── observations
│   ├── scene_description
│   ├── visible_text[]
│   ├── people_or_characters[]
│   └── distinctive_features[]
├── identity_candidates[]
│   ├── name
│   ├── entity_type
│   ├── work_or_affiliation
│   ├── visual_reason
│   └── source_stage
├── reverse_search
│   ├── exact_matches[]
│   ├── visual_matches[]
│   └── repeated_entities[]
├── web_evidence[]
│   ├── candidate
│   ├── supporting_sources[]
│   └── contradicting_sources[]
└── resolution
    ├── confirmed_identity
    ├── confidence_band
    ├── evidence_summary
    └── uncertainty_reason
```

`confidence_band` is an application-level categorical value such as `confirmed`, `uncertain`, or
`unavailable`; it is not a model's uncalibrated numeric self-score.

## Identity Policy

The pipeline follows the rule: prefer not identifying over misidentifying.

### Confirmation Is Allowed

A candidate may be confirmed when at least one of these conditions is satisfied and there is no
strong conflicting evidence:

1. A high-quality exact-match page explicitly identifies the entity, and an independent source
   supports the same identity.
2. Multiple independent Lens results repeatedly identify the same person or character and work,
   and the identity is consistent with the observed visual features.
3. A visual candidate is supported by reliable web evidence connecting that candidate to the image
   context or distinctive features.
4. Clear visible text, a work title, a name, or an official mark in the image identifies the entity,
   and a reliable source verifies the relationship.

Domain repetition alone does not count as independent support. Mirrored or syndicated copies from
the same origin count as one source.

### Confirmation Is Forbidden

The resolver must return uncertain when:

- only the visual model proposes the identity;
- only one weak repost, aggregator, forum post, or untitled image page supports it;
- Lens results conflict materially;
- matches share only weak traits such as art style, hair color, clothing, or pose;
- results may depict cosplay, fan art, AI-generated art, lookalikes, or a different character;
- a real person's face has only similarity results without reliable public context;
- the deadline is reached before evidence crosses the confirmation threshold.

### Real People

- Public figures may be identified only when strong public-source evidence satisfies the same
  confirmation policy.
- Private or unknown people must not be identified through facial similarity, social-profile
  discovery, or inferred personal information.
- The system may describe visible appearance, actions, expression, and scene without inferring
  sensitive traits such as ethnicity, religion, health, sexual orientation, or exact age.

### Fictional Characters

When confirmed, the pipeline may provide the character name, originating work, and concise verified
character information relevant to the user's question.

## Result Passed To The Main Model

A confirmed result should be formatted as concise evidence, for example:

```text
视觉观察：画面中是一名银发动画角色，背景有游戏界面元素。
可见文字：……
身份判断：较可靠地识别为《作品名》中的“角色名”。
判断依据：两个独立来源与画面特征一致，其中包含一个高质量相同图片结果。
不确定项：具体章节或截图时间无法确认。
```

An uncertain result should be explicit:

```text
视觉观察：画面中是一名银发动画角色，服装带有黑色装甲元素。
可见文字：……
身份判断：无法可靠确认。搜索结果存在冲突候选，请勿猜测具体身份。
```

The main roleplay prompt must state that uncertain candidates cannot be rewritten as confirmed facts.

## Concurrency And Deadline

`VISION_PIPELINE_TIMEOUT_SECONDS` defines one deadline for the complete vision stage. Component
timeouts are caps inside that deadline, not additive budgets.

Recommended default flow:

1. During approximately the first two seconds, download and normalize each selected image.
2. After normalization, start visual analysis and R2 upload concurrently.
3. Start Lens as soon as either a permitted original URL is ready or the R2 signed URL is available.
4. Merge candidates when visual analysis and usable Lens results arrive.
5. Use the remaining budget to run web verification for at most two strong candidates.
6. Resolve completed evidence before the shared deadline.
7. At the deadline, cancel unfinished optional tasks and resolve only from completed evidence.
8. Perform best-effort R2 deletion after the user-facing result is no longer waiting on it.

The implementation must pass remaining time into each operation and avoid starting an optional
request when insufficient time remains for it to be useful.

## Multiple Images

- Default `VISION_PIPELINE_MAX_IMAGES=2`.
- Each image receives its own evidence record and reverse-image request.
- Images run concurrently within bounded semaphore limits.
- The whole message shares one pipeline deadline.
- Images beyond the limit remain represented by ordinary message markers but are not analyzed.
- The final context labels evidence by image order to prevent cross-image identity confusion.

## Search Result Normalization

Before model consumption, deterministic code must:

- separate exact and visual matches;
- canonicalize result URLs and domains;
- strip tracking parameters when safe;
- remove empty results and obvious duplicates;
- collapse same-domain repetitions;
- detect mirrored or syndicated pages where practical;
- retain bounded result counts, defaulting to five exact matches and ten visual matches;
- record source quality as a feature, not as a sufficient identity verdict.

Official sites, recognized reference databases, reputable publishers, and primary source pages may
receive stronger weight. Social media, forums, repost sites, and aggregators may provide supporting
context but cannot confirm an identity by themselves.

## Cache

Use the normalized image SHA-256 as the primary cache key.

Cache separately:

- structured visual observations;
- normalized Lens results;
- final identity resolution.

Defaults:

- `VISION_PIPELINE_CACHE_TTL_SECONDS=86400`;
- no raw image bytes;
- no signed URLs;
- no complete third-party raw responses.

Cache entries include a version derived from the visual prompt/schema version, model name, Lens
parser version, resolver-policy version, and relevant configuration. A version change invalidates
incompatible entries automatically.

A valid final-resolution cache hit may skip visual analysis, R2, Lens, and web verification only
when its resolver-policy version, model version, parser version, and evidence schema all match the
current runtime. Partial cache hits may reuse completed safe stages while still respecting the
current deadline and policy version.

## Failure And Degradation

- Visual analysis fails, Lens succeeds: describe only what reliable Lens evidence supports; identity
  still requires the normal threshold.
- Lens fails, visual analysis succeeds: return scene and OCR observations, but do not confirm a
  visual-only identity.
- Web search fails: confirm only if Lens evidence independently satisfies a strong confirmation
  condition; otherwise remain uncertain.
- Original QQ URL is unreachable to Lens: retry with R2 when ready and time permits.
- R2 fails: continue visual analysis and use the original URL if Lens can fetch it.
- Cache fails: continue uncached without failing the reply.
- Pipeline deadline expires: cancel unfinished tasks and return the strongest already completed safe
  result.
- Every external service fails: return an unavailable vision result so the main model can answer only
  from textual chat context without exposing internal error details to the user.

## Configuration

Proposed configuration:

```dotenv
VISION_MODEL_ENABLED=true
VISION_MODEL_API_BASE=https://your-vision-provider.example/v1
VISION_MODEL_API_KEY=replace-with-vision-api-key
VISION_MODEL_NAME=replace-with-vision-model
VISION_MODEL_TIMEOUT_SECONDS=8
VISION_MODEL_ENABLE_THINKING=false

VISION_PIPELINE_TIMEOUT_SECONDS=15
VISION_PIPELINE_MAX_IMAGES=2
VISION_PIPELINE_CACHE_TTL_SECONDS=86400
VISION_PIPELINE_MAX_DOWNLOAD_BYTES=10485760
VISION_PIPELINE_MAX_IMAGE_PIXELS=20000000

SERPAPI_API_KEY=replace-with-serpapi-key
SERPAPI_LENS_ENABLED=true
SERPAPI_SEARCH_ENABLED=true
SERPAPI_TIMEOUT_SECONDS=8
SERPAPI_LENS_EXACT_LIMIT=5
SERPAPI_LENS_VISUAL_LIMIT=10
SERPAPI_WEB_CANDIDATE_LIMIT=2

VISION_TEMP_STORE_BACKEND=r2
R2_ACCOUNT_ID=replace-with-r2-account-id
R2_ACCESS_KEY_ID=replace-with-r2-access-key-id
R2_SECRET_ACCESS_KEY=replace-with-r2-secret-access-key
R2_BUCKET=replace-with-private-bucket
R2_PRESIGNED_URL_SECONDS=300
R2_OBJECT_PREFIX=vision-temp/
```

The implementation may add narrowly necessary concurrency and minimum-remaining-budget settings,
but should avoid exposing every internal constant as configuration before production evidence shows
it is needed.

Remove the obsolete configuration path:

- `VISION_MODEL_MODE`;
- `VISION_MODEL_SEARCH_INPUT`;
- `VISION_MODEL_ENABLE_SEARCH`;
- `VISION_MODEL_SEARCH_TIMEOUT_SECONDS`.

Secrets remain only in the server `.env`. Examples and tests use placeholders.

## Observability

Trace or metric data should include:

- cache hit type;
- download and preprocessing duration;
- normalized byte size and dimensions without image content;
- visual-analysis duration and status;
- R2 upload, signing, and deletion status;
- Lens duration, retry path, exact-match count, and visual-match count;
- web-search query count and duration;
- candidate count;
- resolver rule identifier for confirmation or rejection;
- overall duration, deadline exhaustion, and cancelled stages;
- sanitized provider status and error type.

Trace data must not include:

- image bytes or Base64;
- signed R2 URLs;
- API keys or authorization headers;
- unredacted QQ URL query strings;
- complete raw third-party responses.

Add or extend an offline aggregation utility to calculate P50, P90, and P95 pipeline duration,
stage success and timeout rates, cache hit rate, confirmation versus conservative-rejection rate,
and the contribution of Lens and web evidence to final resolutions.

## Testing

### Unit Tests

Cover:

- download byte limits and invalid content;
- safe decoding, orientation, resizing, and pixel limits;
- normalized-image hashing;
- SerpApi Lens exact and visual result parsing;
- URL and domain normalization;
- duplicate and same-origin collapse;
- candidate extraction and merge behavior;
- confirmation and rejection rules;
- visual-only candidates never becoming confirmed identities;
- conflicting search evidence producing uncertainty;
- private-person identity refusal;
- shared deadline enforcement and cancellation;
- R2 cleanup on success, failure, cancellation, and timeout;
- cache versioning and TTL behavior;
- trace redaction.

### Contract Tests

Store small, sanitized, manually curated SerpApi response fixtures. Fixtures must exclude API keys,
private image URLs, and unnecessary full responses. Tests verify compatibility with the response
fields used by the parser.

### Service Tests

Verify:

- messages that do not trigger a reply do not invoke the vision pipeline;
- triggered private and explicitly addressed group images do invoke it;
- stored vision context remains scoped to the same conversation behavior as today;
- confirmed and uncertain results are formatted distinctly;
- the main model cannot receive an uncertain identity as a confirmed fact;
- multiple images remain labeled and separated;
- vision failure does not block text fallback.

### Real Evaluation

Before production enablement, run a manual evaluation set of approximately 20 to 50 non-private
images covering:

- anime and game characters;
- public figures;
- ordinary private people;
- memes;
- screenshots and OCR-heavy images;
- cosplay;
- fan art;
- AI-generated art;
- low-resolution or cropped images;
- deliberately similar but incorrect characters.

Record end-to-end vision duration, correct confirmations, wrong confirmations, conservative
rejections, useful descriptions, and service failures. Wrong confirmations are the highest-severity
metric. Tune thresholds and timeout only from recorded evidence.

## Migration

1. Keep the service-facing vision protocol but replace its implementation with `VisionPipeline`.
2. Add typed evidence records and deterministic resolver policy.
3. Add image preprocessing and cache support.
4. Add the R2 temporary-store abstraction and backend.
5. Add SerpApi Lens and Google Search clients with sanitized contract fixtures.
6. Replace free-form visual output with structured visual analysis that includes the user question.
7. Remove the Qwen Responses API built-in image-search and web-search implementation.
8. Update service prompt formatting, tests, `.env.example`, `README.md`, and
   `docs/deployment.md`.
9. Deploy with the vision feature disabled until required model, SerpApi, and R2 settings pass a
   startup validation or explicit diagnostic command.
10. Run the real evaluation set, then enable production vision and tune
    `VISION_PIPELINE_TIMEOUT_SECONDS` from observed P95 behavior.

The old implementation remains available in Git history and is not maintained as a parallel runtime
path.

## Security And Privacy

The user has approved submission of every image that has already entered the allowed vision flow to
SerpApi/Google Lens and temporary object storage. This approval does not expand the trigger policy:
unaddressed group images that the bot ignores must not be uploaded or searched.

Additional controls:

- Use TLS for all providers.
- Keep the R2 bucket private and expose only short-lived signed object URLs.
- Use unpredictable object names unrelated to QQ identifiers or filenames.
- Delete temporary objects promptly and configure lifecycle cleanup.
- Bound download size, decoded dimensions, redirects, and request time.
- Do not fetch arbitrary model-generated URLs; only process URLs extracted from allowed OneBot media
  segments and normalized search-result URLs used as textual evidence.
- Redact secrets and sensitive URL parameters in traces and final answers.

## Success Criteria

The design is successful when:

- the vision stage obeys one configurable deadline, defaulting to 15 seconds;
- repeated images can use a complete cached resolution without new provider calls;
- identity is never confirmed from visual-model resemblance alone;
- Lens and web-search execution is explicit, structured, and traceable;
- conflicting or weak evidence produces an uncertain answer;
- public characters and public figures receive useful verified identity information when evidence is
  strong;
- ordinary private people are described but not identified;
- provider failures preserve a useful text or visual-description fallback;
- production traces expose latency and decision quality without exposing images, secrets, or signed
  URLs.
