# Controlled Agent Media Pipeline Design

## Goal

Refactor the current roleplay bot toward a controlled agent pipeline while adding image and
sticker output support.

The pipeline must keep production chat safety predictable:

- Deterministic rules decide whether the bot may reply.
- The model runs only after the existing trigger policy has decided to reply.
- Active image or sticker replies are only attached to an existing model text reply.
- Repeat (`+1`) media replies reuse temporary media from the current chat flow and do not persist
  remote QQ/NapCat media.
- Active images and stickers come only from a server-persistent asset library.

The current repository state is tagged as `v1.0`; this work is the next iteration.

## Non-Goals

- Do not build a fully autonomous model agent that decides when to speak in groups.
- Do not let the model emit raw CQ codes, arbitrary file paths, or OneBot message segments.
- Do not download and persist temporary group images for repeat replies.
- Do not commit real sticker packs, QQ account data, generated cache files, API keys, or other
  server-only artifacts.
- Do not change the existing public trigger behavior except where media repeat adds a matching
  image or face output.

## Current State

The plugin currently renders text replies with `MessageSegment.text(reply)`. TTS is the only
non-text output branch, using `MessageSegment.record(...)` when voice rendering succeeds.

Incoming image, video, voice, face, and file segments are summarized into text for model context.
Vision support can describe incoming media, but this is input understanding, not output rendering.

Repeat replies currently compare recent stored message text and return that same text. For media
messages, the repeat path therefore repeats the text marker such as `[image: ...]`, not the
original image or QQ face.

## Recommended Architecture

Use a controlled agent pipeline with these boundaries:

1. `TriggerPolicy`
   - Keeps group whitelist, `/bot on`, mute, direct mention, reply-to-bot, follow-up, keyword, and
     random trigger decisions deterministic.
   - Private messages continue to reply directly.
   - Search, vision, stickers, and TTS must not bypass this decision.

2. `RepeatPolicy`
   - Runs before model calls.
   - Short-circuits normal model handling for eligible repeat chains.
   - Supports text, image, and QQ face repeat signatures.
   - Requires the existing minimum threshold, multiple users, group enabled state, and cooldown.

3. `AgentRunner`
   - Runs only after `TriggerPolicy` says the bot should reply.
   - Owns prompt construction and model invocation.
   - Receives tool context from controlled code-selected tools such as time, Tavily search, persona
     source lookup, and vision summary.
   - Produces model text, not transport-specific segments.

4. `ReplyEnhancer`
   - Runs after model text is accepted by guardrails.
   - Optionally appends active image or sticker messages from the persistent server asset library.
   - Never creates a reply by itself; active media is attached only to a model-approved text reply.

5. `OutgoingReply`
   - A transport-neutral reply object containing ordered outbound messages.
   - Supports separate messages so active replies can send text first and image/sticker second.
   - Supports text, image, face, and record messages without exposing OneBot details to the service
     layer.

6. `TransportRenderer`
   - Lives in the NoneBot plugin boundary.
   - Converts `OutgoingReply` messages into OneBot `MessageSegment.text`, `image`, `face`, or
     `record` sends.
   - Sends each outbound message in order as a separate `bot.send(...)` call.

## Outgoing Reply Model

Introduce transport-neutral dataclasses similar to:

```python
@dataclass(frozen=True)
class OutgoingMessage:
    kind: Literal["text", "image", "face", "record"]
    text: str = ""
    file: str = ""
    url: str = ""
    face_id: str = ""
    source: str = ""


@dataclass(frozen=True)
class OutgoingReply:
    messages: list[OutgoingMessage]
    source: str
```

Rules:

- A normal model reply returns one text message.
- An active sticker reply returns two messages: text first, image second.
- A text repeat returns one text message.
- An image repeat returns one image message using the temporary media reference.
- A face repeat returns one face message using the QQ face id.
- TTS may render the text message as record at the plugin boundary or through a later renderer
  step. The first implementation may keep existing TTS behavior and skip active sticker append when
  voice is sent if that keeps the migration smaller.

## Active Image And Sticker Library

Active media comes from a server-persistent library.

Recommended server path:

```text
/opt/qq-rolebot/stickers/
```

Recommended structure:

```text
/opt/qq-rolebot/stickers/
  manifest.yaml
  chongyue/
    calm-01.webp
    amused-01.jpg
```

Manifest shape:

```yaml
items:
  - id: calm-01
    file: chongyue/calm-01.webp
    tags: [calm, reply]
    weight: 1
```

Configuration:

- `MEDIA_REPLY_ENABLED`: enables active media append.
- `MEDIA_REPLY_PROBABILITY`: percentage chance after a successful model text reply.
- `MEDIA_STICKER_ROOT`: persistent server asset root, defaulting to `stickers` locally and
  `/opt/qq-rolebot/stickers` in production docs.
- `MEDIA_STICKER_MANIFEST`: optional manifest path, defaulting to
  `${MEDIA_STICKER_ROOT}/manifest.yaml`.

Storage and deployment:

- Real production sticker assets are server-only and excluded from git.
- The deploy script preserves `/opt/qq-rolebot/stickers` or the in-app `stickers/` directory under
  `/opt/qq-rolebot`.
- The repository may include a small example manifest if needed, but not private or large assets.

Selection behavior:

- The first implementation should use deterministic code-side selection from configured tags and
  weights.
- The model must not choose arbitrary file paths.
- Later iterations can let the model suggest a semantic tag, but code still maps tags to known
  manifest entries.

## Temporary Repeat Media

Incoming message parsing should preserve repeat-capable media references separately from text
summaries.

For image repeat:

- Use the current OneBot image `file` or HTTP `url` if available.
- Do not download the image.
- Do not persist temporary media in repository files or long-lived storage.
- Keep repeat-capable temporary media references in an in-process short-lived repeat tracker rather
  than SQLite message history.
- If the temporary reference cannot be rendered, the repeat output may fall back to text repeat or
  no media output.

For QQ face repeat:

- Preserve the `face` segment id.
- Repeat with `MessageSegment.face(id)` at the renderer boundary.

Repeat matching should compare a stable repeat signature:

- Text: normalized message text.
- Image: image marker or repeat media reference.
- Face: face id.

The existing repeat constraints remain in force:

- group must be whitelisted and enabled;
- message must be unaddressed;
- group must not be muted;
- chain length must satisfy `REPEAT_REPLY_THRESHOLD`;
- at least two users must participate;
- same repeat signature is cooled down for 10 minutes.

## Data Flow

Group addressed or triggered message:

1. Plugin parses OneBot event into `IncomingMessage`, including media summaries and repeat media
   references.
2. Service stores incoming context as before.
3. `RepeatPolicy` checks repeat eligibility. If matched, return an `OutgoingReply` and skip tools
   and model.
4. `TriggerPolicy` decides whether normal model handling should continue.
5. Controlled tools build context for time, search, persona sources, and vision when applicable.
6. `AgentRunner` builds messages and calls the chat model.
7. Guardrails clean the model text.
8. `ReplyEnhancer` optionally appends a persistent sticker image.
9. Service stores text representation of successful bot outputs for context.
10. Plugin renders ordered messages as separate sends.

Private message:

- Skip group enablement checks as today.
- Run controlled tools and model normally.
- Active media append can be enabled for private messages under the same `MEDIA_REPLY_ENABLED` and
  probability settings.

## Error Handling

- If active sticker manifest loading fails, log/trace the error and continue with text-only replies.
- If a selected sticker file is missing, skip that sticker and continue with text-only replies.
- If the text send succeeds but image send fails, do not retract or add a new apology message.
- If image repeat rendering fails, do not persist the failed temporary reference.
- Debug traces may record sticker ids, tags, and relative paths, but must not include secrets or
  login URLs.

## Testing Strategy

Unit tests:

- Config parses media settings and rejects invalid probabilities.
- Sticker library loads a manifest, ignores missing files, and selects weighted assets.
- `RepeatPolicy` returns text, image, and face `OutgoingReply` objects under existing threshold,
  multi-user, group enabled, and cooldown rules.
- Active media append only happens after a successful model text reply.
- Active media append never creates a standalone reply when trigger policy or guardrails suppress
  text.

Plugin tests:

- Renderer sends text and image as separate `bot.send(...)` calls in order.
- Renderer sends temporary repeat image with `MessageSegment.image(...)`.
- Renderer sends QQ face repeat with `MessageSegment.face(...)`.
- Existing TTS fallback behavior remains covered.

Docs and deployment tests:

- `.env.example`, `README.md`, and `docs/deployment.md` document the new settings and server asset
  directory.
- `scripts/deploy_server.sh` preserves the sticker directory.
- `git diff --check` must pass for docs-only changes.

## Migration Plan

Implement in small steps:

1. Add `OutgoingReply` and a renderer while keeping text behavior equivalent.
2. Move existing text replies onto `OutgoingReply`.
3. Add repeat media references to incoming message parsing.
4. Extend repeat logic for image and face outputs.
5. Add sticker config and persistent sticker library loading.
6. Add `ReplyEnhancer` for active image append after model text.
7. Update deployment preservation and docs.

This sequence keeps the bot usable after each step and limits changes to one boundary at a time.

## Initial Decisions

- TTS plus active image behavior should start conservative: when TTS successfully sends a record,
  skip active image append. This can be revisited later.
- The first active sticker selector should be code-driven by tags and weights, not model tool-call
  driven. A later version can let the model suggest tags after the controlled pipeline is stable.
