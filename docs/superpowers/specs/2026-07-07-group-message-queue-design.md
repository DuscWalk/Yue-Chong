# Per-Group Message Queue Design

## Goal

Make group chat replies stable under high-frequency mentions by serializing message processing per
group. The bot should avoid concurrent model calls for the same group, preserve reply order for
queued messages, and keep other groups responsive.

## Current Behavior

`qq_rolebot/plugins/roleplay_chat.py` calls `service.handle(...)` directly from the NoneBot message
handler. When many group messages mention the bot, each event can enter the model/tool/TTS path at
the same time. The project has a `RateLimiter`, but the current service path does not call it.

The existing `message_context` table stores recent context only. It is not a reply queue.

## Proposed Behavior

Add a per-group queue layer in the plugin path:

- Private messages keep the current direct handling path.
- Group messages are submitted to a queue keyed by `group_id`.
- Each group has one worker task that processes queued messages in FIFO order.
- Different groups can process concurrently because each group has its own worker.
- Admin commands are queued with normal group messages so same-group state changes stay ordered.
- A currently processing message is never canceled by queue overflow.

## Overflow Policy

Add a configurable queue size, recommended default `GROUP_QUEUE_MAX_SIZE=100`.

When a group's pending queue is full and a new group message arrives:

- Drop the oldest pending message for that group.
- Enqueue the new message.
- Do not send a group notification for the dropped message.
- Log a sanitized warning with the group id and queue size, without message text or secrets.

This keeps the bot responsive to newer conversation turns while bounding memory use. It does not
guarantee replies for messages that were dropped before processing.

## Components

### `GroupMessageQueue`

A small async queue manager responsible for:

- creating one queue and one worker per group;
- accepting queue items from the plugin;
- dropping the oldest pending item on overflow;
- invoking the supplied async processor for each item;
- catching per-item exceptions so the worker continues;
- shutting down workers during application shutdown if practical.

The queue manager should be independent of NoneBot-specific event parsing where possible, so its
ordering and overflow behavior can be tested without a live adapter.

### Plugin Integration

`handle_message` should:

- build the existing `IncomingMessage`;
- handle private messages directly as it does today;
- submit group messages to `GroupMessageQueue`;
- let the queued processor call `service.handle(...)`, optional TTS rendering, and `bot.send(...)`.

The queued processor should preserve the current text fallback when TTS fails.

### Configuration

Add `group_queue_max_size` to `Settings`, loaded from `GROUP_QUEUE_MAX_SIZE`.

Validation:

- must be greater than 0;
- default should be `100`.

Update `.env.example`, `README.md`, and deployment docs if they describe runtime tuning knobs.

## Error Handling

If `service.handle(...)`, TTS rendering, or `bot.send(...)` raises, log a sanitized exception and
continue to the next queued item. If the model returns `ok=False`, keep the current behavior of no
reply for that message.

Overflow only drops pending items, not the item currently being processed.

## Testing

Add focused tests before implementation:

- same-group items are processed one at a time in submit order;
- different groups can process concurrently;
- queue overflow drops the oldest pending item and keeps the newest item;
- a processor exception does not stop later items from being processed;
- plugin-level behavior submits group messages to the queue while private messages still use direct
  handling;
- config parsing accepts the default and rejects invalid queue sizes.

Run the standard checks before completion:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m ruff check .
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q
git diff --check
```

