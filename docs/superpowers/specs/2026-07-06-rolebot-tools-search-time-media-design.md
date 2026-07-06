# QQ Rolebot Tools, Search, Time, And Media Design

## Goal

Extend the existing NapCatQQ + NoneBot roleplay bot with a small tool layer that lets
Chongyue answer time-sensitive questions, use approved external knowledge sources, and
gradually handle QQ multimedia messages while preserving the current roleplay behavior.

The first implementation should focus on safe, useful text behavior:

- Current time queries.
- Tavily-backed web search for explicitly addressed and time-sensitive/search-intent messages.
- Persona source lookup from `personas/default.yaml`, starting with the PRTS Chongyue page.
- A clean internal interface for later voice, emoji, image, and file support.

Voice and richer media should be designed now but can be implemented after the text tool layer
is stable.

## Current Context

The bot currently receives OneBot V11 messages through NapCatQQ, converts plain text messages
into `IncomingMessage`, applies whitelist/trigger/rate policies, builds persona prompts, calls
an OpenAI-compatible model, filters the response, and sends a text reply.

The current message extraction uses `event.get_plaintext()`, so non-text segments are mostly
invisible to the service layer. The plugin sends only `MessageSegment.text(reply)`.

The deployed persona file uses a long roleplay schema with fields such as `Profile`, `Skills`,
`Background`, `Rules`, `Prologue`, and `Examples`.

## User-Confirmed Requirements

- Web search uses Tavily.
- The Tavily API key is secret and must live only in environment variables, for example
  `TAVILY_API_KEY`.
- In group chat, open web search is allowed only when the message is clearly addressed to
  Chongyue:
  - the message mentions the bot with `@`, or
  - the message is a reply to one of the bot's messages.
- In private chat, the message is considered clearly addressed to Chongyue.
- Search should trigger for explicit search intent and time-sensitive intent.
- Time-sensitive terms such as "today", "now", "latest", "news", "weather", "price", and
  "recent" should trigger search even if the user did not explicitly say "search".
- The Chinese implementation must include equivalent Chinese trigger phrases. Examples are
  encoded here as Unicode escapes to avoid Windows codepage corruption:
  - Search intent: `\u67e5\u4e00\u4e0b`, `\u641c\u4e00\u4e0b`,
    `\u5e2e\u6211\u67e5`, `\u641c\u7d22`, `\u7f51\u4e0a\u8bf4`,
    `\u8d44\u6599`, `\u5b98\u7f51`, `\u662f\u771f\u7684\u5417`,
    `\u600e\u4e48\u56de\u4e8b`.
  - Time-sensitive intent: `\u4eca\u5929`, `\u73b0\u5728`,
    `\u6700\u65b0`, `\u65b0\u95fb`, `\u5929\u6c14`, `\u4ef7\u683c`,
    `\u6700\u8fd1`, `\u521a\u521a`, `\u4eca\u5e74`, `\u672c\u5468`.
- Add `https://prts.wiki/w/%E9%87%8D%E5%B2%B3` to `personas/default.yaml` as an approved
  persona source.
- For character-specific questions, the bot may query approved persona sources even without
  generic search keywords, so that the roleplay is more faithful.
- Voice style is authorized by the user. The system may later support a Chongyue-style TTS
  voice, but authorization assets and keys must not be committed or logged.

## Recommended Approach

Use a hybrid tool router.

1. A `ToolRouter` decides which tools are allowed and useful for a message.
2. A `TimeTool` answers current time directly.
3. A `TavilySearchTool` performs open web search for explicitly addressed messages with search
   or time-sensitive intent.
4. A `PersonaSourceTool` fetches and summarizes only URLs listed in `personas/default.yaml`.
5. Tool outputs are injected into the model prompt as compact context. The model still speaks
   as Chongyue and produces the final reply.

This keeps triggering rules deterministic while letting the model use retrieved facts naturally.

## Alternatives Considered

### Always Let The Model Decide

The model could decide when to search from the prompt alone. This is flexible, but too easy to
over-trigger in group chat and consume search quota.

### Command-Only Search

Only `/search keyword` would be simple and cheap. It would miss natural questions like
`@bot today news` or `@bot latest weather`, and it would feel less conversational.

### Recommended Hybrid Routing

Use deterministic routing before the model. It respects group chat boundaries, supports natural
questions, and keeps search cost predictable.

## Persona Sources

Add a `Sources` section to `personas/default.yaml`:

```yaml
Sources:
  - name: PRTS Chongyue
    url: https://prts.wiki/w/%E9%87%8D%E5%B2%B3
    purpose: character profile, voice records, archive, and line-style reference
```

The loader should preserve this as structured data on the `Persona` object.

`PersonaSourceTool` may use these sources when a message is clearly about the role, for example:

- "who are you"
- "your background"
- "Nian, Dusk, or Ling"
- "Yumen"
- "your voice lines"
- "Chongyue lore"
- "your archive"

The Chinese implementation should detect the equivalent Chinese terms from the persona file and
common role questions. The tool must not browse arbitrary domains for persona lookup. It should
fetch only configured source URLs.

## Search Triggering

### Addressing Gate

Open web search may run only if one of these is true:

- `IncomingMessage.is_private` is true.
- The group message mentions the bot.
- The group message replies to a bot message.

Random group replies must not trigger open web search.

### Search Intent

After the addressing gate passes, open search may run if the text contains either explicit
search intent or time-sensitive intent.

The keyword list should be configuration-friendly so it can be adjusted without rewiring the
service.

### Time Query

Current time should not need Tavily. If a message asks for the current time, current date, or
similar, use `TimeTool`.

If a message asks for weather, news, price, or other external current facts, use Tavily.

## Prompt Integration

Tool results should be passed into `build_chat_messages` as an optional tool context section.

The prompt should instruct the model:

- Use retrieved facts when present.
- Keep the reply in persona.
- Do not mention API names, tool internals, or hidden routing.
- If search fails, say briefly that the current information was not found, then answer cautiously
  if possible.

Search result context should be short:

- Query.
- 3 to 5 results.
- Title, URL, short snippet/content.
- Optional answer field if Tavily returns one.

The final QQ reply should remain plain text unless a later media renderer decides to send a
voice/image/file segment.

## Media Recognition

Introduce a richer incoming message representation later, without breaking current text behavior:

- Text segments become readable text.
- `image` segments become `[image]` with metadata if available.
- `record` segments become `[voice]` and can optionally be transcribed by ASR.
- `face` segments become `[emoji]`.
- File-related segments become `[file: name]` when NapCat exposes metadata.
- Unknown segments become `[unsupported segment: type]`.

The first implementation may only preserve segment summaries and keep text replies.

## Media Sending

Future outgoing replies should support a typed response object instead of only `str`:

- `TextReply(text)`
- `VoiceReply(text, audio_path)`
- `ImageReply(path_or_url)`
- `FileReply(path)`

The existing plugin can render `TextReply` through `MessageSegment.text`. Voice/image/file
rendering can be added behind feature flags.

## Voice Design

Because the user states the voice is authorized, the system may support a Chongyue-style TTS
profile later.

Constraints:

- Voice model files, samples, or vendor keys must not be committed.
- Generated voice should be stored in a temporary cache and cleaned up.
- Voice replies should be opt-in by command or probability setting, not default for every message.
- The text used for TTS should be short and already filtered by guardrails.
- If TTS fails, fall back to text.

Possible triggers:

- Explicit phrases equivalent to "say it by voice" or "send a voice message".
- Admin setting: `/bot voice on|off`.
- Optional low-probability voice reply for private chat after the feature is stable.

## Configuration

Add environment variables:

- `TAVILY_API_KEY`
- `TAVILY_API_BASE`, default `https://api.tavily.com`
- `SEARCH_MAX_RESULTS`, default `5`
- `SEARCH_TIMEOUT_SECONDS`, default `10`
- `SEARCH_COOLDOWN_SECONDS`, default `20`
- `TOOLS_ENABLE_SEARCH`, default `true`
- `TOOLS_ENABLE_PERSONA_SOURCES`, default `true`
- `TOOLS_ENABLE_TIME`, default `true`

Do not put real API keys in `.env.example`, docs, tests, or logs.

## Error Handling

- Missing Tavily key: search is disabled and the bot answers without search.
- Tavily timeout or HTTP error: log a sanitized warning and answer cautiously.
- Empty search results: tell the model no current result was found.
- Persona source fetch error: use local persona text and avoid pretending to know sourced details.
- Rate-limited search: skip search and continue normal reply.

## Rate Limits And Cost Control

Open search should have separate limits from chat reply rate limits:

- Per-user cooldown.
- Per-group cooldown.
- Optional daily max counter later if needed.

Persona source lookup can be cached longer than web search because PRTS character data changes
slowly.

## Testing

Unit tests should cover:

- Addressing gate for group/private messages.
- Search keyword detection.
- Time query detection.
- Persona source trigger detection.
- Tavily client success/failure parsing with mocked HTTP responses.
- Prompt includes tool context when provided.
- Missing API key disables search without crashing.
- Segment summary extraction for image, record, face, and unknown segments.

Integration smoke tests should cover:

- A private "today news" message triggers search context.
- A group message with no mention does not search.
- A group `@bot today news` message searches.
- A role question can query the configured PRTS source.

## Deployment

Deployment steps:

1. Add the new code and tests locally.
2. Run unit tests and lint.
3. Add `TAVILY_API_KEY` to `/opt/qq-rolebot/.env` on the server.
4. Deploy code and updated `personas/default.yaml`.
5. Restart `qq-rolebot.service`.
6. Verify the bot reconnects to NapCat and search-triggering messages behave correctly.

## Out Of Scope For First Implementation

- Full ASR for arbitrary voice messages.
- Full TTS voice generation and QQ voice sending.
- File upload/download workflows.
- Sticker generation.
- Autonomous browsing for unrelated roleplay messages.
- Any public logging or storage of secret keys, voice samples, or generated private media.

## Open Decisions Resolved

- Search provider: Tavily.
- Search trigger: explicit addressing plus search/time-sensitive intent.
- Persona source: add PRTS Chongyue URL to `default.yaml`.
- Persona source lookup may run without generic search keywords for role-specific questions.
- Voice authorization exists, but voice implementation can follow after the text tool layer.
