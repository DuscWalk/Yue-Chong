# NapCatQQ Roleplay Group Bot Design

Date: 2026-07-05

## Goal

Build a QQ group chat bot that logs in through a QQ alternate account via NapCatQQ, behaves like a defined role/persona, and participates in daily group conversation without overwhelming the group.

The first version should feel like a restrained group member: it replies when mentioned, occasionally joins naturally when enabled, remembers short conversation context, and can be controlled by an administrator.

## Constraints

- The bot uses a QQ alternate account through NapCatQQ and OneBot 11. This is not the same risk profile as the official QQ Bot platform, so the implementation must avoid spam-like behavior and support quick shutdown.
- The bot runs on the user's Ubuntu server.
- The local workspace currently has no existing bot project structure and is not a git repository.
- The initial storage layer is SQLite for simplicity.
- The model provider is configured through environment variables using an OpenAI-compatible chat API shape where possible, so the backend can be swapped later.

## Non-Goals

- No mass messaging, advertisement behavior, automatic group joining, or bypassing platform restrictions.
- No attempt to make the bot indistinguishable from a real human for deception.
- No complex web dashboard in the first version.
- No long-term vector memory in the first version; keep memory simple and inspectable.

## Recommended Approach

Use NapCatQQ as the QQ account gateway, expose OneBot 11 over WebSocket, and run a Python bot service using NoneBot2 with the OneBot adapter.

This gives us a clean split:

- NapCatQQ owns QQ login and message transport.
- NoneBot2 owns event routing, command handling, permissions, and plugin structure.
- A small application layer owns persona prompts, context memory, rate limits, and model calls.

## Architecture

```text
QQ group
  -> QQ alternate account logged in by NapCatQQ
  -> OneBot 11 WebSocket event stream
  -> NoneBot2 + OneBot adapter
  -> message router
  -> trigger policy
  -> context memory
  -> persona prompt builder
  -> model client
  -> response guardrails
  -> OneBot send_group_msg
  -> QQ group
```

## Components

### NapCatQQ Gateway

NapCatQQ runs on the server, logs in to the QQ alternate account, and exposes a OneBot 11 connection. The bot service connects over WebSocket.

Configuration should include:

- QQ account login handled outside the Python bot.
- OneBot WebSocket endpoint and access token.
- Only the required OneBot actions and events enabled.

### Bot Runtime

The Python service uses NoneBot2. It should include:

- OneBot adapter setup.
- Startup configuration validation.
- Group whitelist loading.
- Admin user loading.
- Plugin registration.

### Message Router

The router receives group messages and classifies them into:

- Administrator commands.
- Direct mentions or replies to the bot.
- Keyword-triggered messages.
- Random participation candidates.
- Ignored messages.

Private messages are ignored in the first version unless needed for admin control later.

### Trigger Policy

The bot replies when:

- It is directly mentioned.
- A configured keyword appears.
- Random participation is enabled for the group and a probability check passes.

Defaults:

- Direct mention: always reply.
- Keyword trigger: reply if not rate-limited.
- Random participation: 8% chance, only when group mode is enabled.
- Group limit: maximum 3 generated replies per group per 60 seconds.
- User cooldown: avoid repeatedly replying to the same user within a short window.

### Persona Layer

The persona is configured in a plain text or YAML file. It defines:

- Character name.
- Speaking style.
- Relationship to the group.
- Things the character likes or dislikes.
- Hard boundaries: no explicit sexual content, hate, harassment, private-data requests, illegal instruction, or platform-abusive behavior.

The prompt should instruct the model to act like a casual group member, keep messages short, and avoid sounding like customer service.

### Memory

Version 1 uses short, local memory:

- Recent group context: last 20 relevant messages per group.
- Optional per-user nicknames or notes set by admin command.
- No vector database.
- No hidden permanent memory without explicit admin action.

SQLite tables:

- `group_settings`: group enable state, random reply probability, persona name.
- `message_context`: recent message records with group id, user id, nickname, text, timestamp.
- `admin_users`: administrator QQ ids.
- `user_notes`: optional admin-managed notes.
- `rate_limits`: lightweight counters or timestamps.

### Model Client

The model client reads:

- API base URL.
- API key.
- Model name.
- Timeout.
- Maximum output length.

The client should return either a text response or a structured failure result. Failures should not create repeated group messages.

### Response Guardrails

Before sending a model response:

- Trim excessive length.
- Remove empty or whitespace-only output.
- Suppress responses that look like system prompts, logs, stack traces, or policy text.
- Apply a simple sensitive-word blocklist.
- Fail closed if the model call errors repeatedly.

### Admin Commands

Use simple group commands, restricted to configured admin QQ ids:

- `/bot on`: enable this group.
- `/bot off`: disable this group.
- `/bot mute 10m`: silence generated chat temporarily.
- `/bot prob 8`: set random participation probability to 8%.
- `/bot clear`: clear recent group context.
- `/bot status`: show current group settings.

Commands should be short and avoid exposing secrets.

## Data Flow

1. NapCatQQ receives a QQ group message and pushes it to the bot through OneBot WebSocket.
2. NoneBot2 parses the event.
3. The router stores a sanitized summary in recent context.
4. Admin commands are executed immediately if the sender is authorized.
5. Normal messages pass through whitelist, enabled-state, trigger, and rate-limit checks.
6. The prompt builder combines persona settings, recent context, and the triggering message.
7. The model client requests a short reply.
8. Guardrails validate the reply.
9. The bot sends the final response through OneBot.

## Error Handling

- NapCatQQ disconnected: log the error and let the bot reconnect according to adapter behavior.
- Model timeout: silently ignore once, then log; do not spam the group.
- Invalid config: fail at startup with a clear message.
- Database failure: do not send generated replies; log and keep the process alive only if safe.
- Unauthorized admin command: ignore or reply with a short denial depending on configuration.
- Rate-limit hit: do not reply.

## Deployment

Run both services on the Ubuntu server:

- NapCatQQ as the QQ gateway.
- Python bot service as a long-running process, preferably managed by `systemd` or Docker Compose.
- SQLite database stored in the bot project directory or a configured data directory.
- Secrets in `.env`, not committed.

The first deploy does not require a public HTTP endpoint because the preferred connection is local or server-side WebSocket between NapCatQQ and the bot.

## Testing

Testing should cover:

- Trigger policy decisions.
- Rate limiting.
- Admin command permission checks.
- Prompt construction.
- Model client failure behavior.
- Response filtering.
- SQLite persistence for group settings and context.

Integration testing should use sample OneBot group message events before testing against a real QQ group.

## First Implementation Scope

Build only the minimum useful version:

- Create a fresh Python project structure.
- Add NoneBot2 with OneBot adapter.
- Add environment-based config.
- Add SQLite storage.
- Add one persona config.
- Add group whitelist and admin list.
- Add mention replies, keyword replies, random low-probability replies.
- Add admin commands.
- Add unit tests for policy and command logic.
- Add deployment notes for the Ubuntu server.

## Open Decisions Already Chosen

- QQ access route: NapCatQQ.
- Bot framework: NoneBot2.
- Protocol: OneBot 11 WebSocket.
- Storage: SQLite for version 1.
- Runtime target: Ubuntu server.
- Behavior style: restrained daily group roleplay, not an always-reply assistant.
