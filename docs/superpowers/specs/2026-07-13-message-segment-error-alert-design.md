# Message Segment And Error Alert Design

## Goal

Prevent unsupported OneBot message segments from becoming visible text that the bot can
repeat, and prevent runtime exceptions from producing any bot-authored error message in a
group or private chat. Send a sanitized administrator email when an exception is caught.

## Scope

The change covers the message parsing and NoneBot event boundary in the roleplay plugin. It
does not change the vision pipeline, provider retry policy, or ordinary user-facing model
replies. The existing watchdog SMTP conventions are reused; no new mail provider is added.

## Design

### Unsupported segments

`message_segments.summarize_segments` keeps supported text and media summaries, but skips
unknown segment types. A message containing only an unknown segment becomes empty and is
ignored by `build_incoming_message`; it cannot trigger a reply or enter repeat tracking. A
supported text message accompanied by an unknown segment keeps its supported text, without
echoing an implementation placeholder into the conversation.

### Exception boundary

The plugin's locked message handler validates and renders the complete `OutgoingReply` before
the first send. The complete operation is wrapped in one exception boundary covering message
handling, optional voice rendering, and outgoing sends. On failure it:

1. logs the exception with a stable stage label;
2. sends no error text, unsupported segment, or traceback to the originating chat;
3. attempts one asynchronous administrator alert;
4. swallows alert failures after logging them.

The renderer accepts only the existing text, image, face, mface, and record kinds. Unknown
outgoing kinds are skipped and logged as a local warning rather than sent to OneBot.

### Administrator alerts

Add a small `ExceptionNotifier` with an injectable SMTP sender and clock for tests. SMTP
settings use the existing `SMTP_HOST`, `SMTP_PORT`, `SMTP_SSL`, `SMTP_USER`, `SMTP_PASSWORD`,
`ALERT_EMAIL_FROM`, and `ALERT_EMAIL_TO` variables. An empty recipient list disables email but
does not disable exception suppression. `EXCEPTION_ALERT_COOLDOWN_SECONDS` defaults to 600;
the notifier suppresses duplicate alerts by stable stage and exception type during that
window.

Email bodies contain only timestamp, stage, exception type, group/user identifiers, and a
bounded traceback after removing HTTP query strings, data URLs, authorization-like values,
and long opaque tokens. They never contain the incoming message text, media URLs, provider
keys, QQ access tokens, or image bytes.

## Failure behavior

- Parser failure or unsupported input: ignore the unsupported part and continue supported text.
- Service/model/provider exception: no chat output; log and email when configured.
- Outgoing segment construction failure: no segment is sent from that reply; log and email.
- OneBot send failure after a prior segment was sent: stop sending remaining segments; log and
  email. The system cannot retract a segment already accepted by OneBot.
- SMTP failure: log only; never recurse into another alert and never send to the chat.

## Verification

Tests cover unknown segment omission, messages made only of unknown segments, complete outgoing
render validation, exception suppression, SMTP payload redaction, cooldown deduplication, and
SMTP failure isolation. A production check will inspect the service journal and send a
controlled failure only after configuration is enabled; no real exception is deliberately
injected into a group chat.
