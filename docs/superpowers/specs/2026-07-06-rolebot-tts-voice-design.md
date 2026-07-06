# Rolebot TTS Voice Design

## Goal

Add optional voice replies to the NapCatQQ roleplay bot by calling a local TTS HTTP service,
with CosyVoice as the recommended deployment backend.

## Scope

This slice implements the bot-side integration:

- Read TTS settings from environment variables.
- Detect explicit voice requests in private chats and addressed group messages.
- Call a local TTS service over HTTP.
- Store generated audio files under a cache directory.
- Send the generated audio through OneBot as a `record` message segment.
- Fall back to the normal text reply if TTS is disabled, not requested, times out, or fails.

This slice does not install CosyVoice, train or fine-tune a voice model, download voice assets,
or include copyrighted/audio assets in the repository.

Large runtime artifacts such as model weights, container images, reference audio, converted
datasets, and generated voice cache files must live only on the server. The local workspace and
git repository keep code, tests, documentation, and configuration templates only.

## Architecture

The existing chat flow remains the source of truth for whether the bot should reply and what it
should say. Voice is an output rendering choice after `ChatService.handle()` returns a cleaned
text reply.

```text
OneBot event
  -> build IncomingMessage
  -> ChatService.handle()
  -> text reply
  -> VoiceService.maybe_render(incoming, reply)
  -> record segment if audio was generated
  -> text fallback otherwise
```

## Components

### Settings

Add optional configuration:

- `TTS_ENABLED`
- `TTS_API_URL`
- `TTS_TIMEOUT_SECONDS`
- `TTS_TRIGGER_KEYWORDS`
- `TTS_MAX_CHARS`
- `TTS_COOLDOWN_SECONDS`
- `TTS_CACHE_DIR`
- `TTS_SPEAKER`
- `TTS_STYLE`
- `TTS_DIALECT_HINT`

Defaults keep TTS disabled.

### Voice Policy

Voice generation is allowed only when:

- TTS is enabled.
- A text reply already exists.
- The user's message asks for voice using configured keywords.
- Private chat, or group chat addressed by `@`/reply-to-bot.
- Per-scope cooldown allows it.

### TTS Client

`TTSClient` calls `POST {TTS_API_URL}/synthesize` with:

```json
{
  "text": "...",
  "speaker": "chongyue",
  "style": "calm",
  "dialect_hint": "neutral",
  "format": "wav"
}
```

The client accepts raw audio bytes or JSON with base64 audio. A non-2xx response or malformed
response becomes a structured failure, not an exception that breaks message handling.

### Voice Service

`VoiceService` truncates long replies to `TTS_MAX_CHARS`, invokes the TTS client, writes a stable
cache file, records cooldown on success, and returns a local file path for OneBot.

### Plugin Sending

The plugin sends `MessageSegment.record(file=path)` when voice rendering succeeds. Otherwise it
sends the original text reply.

## Deployment

CosyVoice should run as a separate local service, such as `cosyvoice.service`, bound to
`127.0.0.1`. The rolebot process calls only the local HTTP endpoint. The generated cache directory
must be writable by the rolebot service user.

Recommended server-only artifact paths:

- `/opt/cosyvoice` for CosyVoice source/runtime service code.
- `/opt/models/cosyvoice` for model weights.
- `/opt/qq-rolebot/data/voice_refs/chongyue` for authorized reference audio.
- `/opt/qq-rolebot/data/voice_cache` for generated outgoing voice files.

## Testing

Tests cover:

- Settings defaults and overrides.
- Voice request routing and cooldown.
- TTS client handling raw audio, JSON base64 audio, and failures.
- Voice service cache writing and text truncation.
- Plugin sending `record` on generated audio and text on fallback.
