# Group Quoted Replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ordinary group replies quote the triggering QQ message and mention its sender, while excluding repeat and voice replies and applying the quote only to the first rendered outbound message.

**Architecture:** Keep trigger policy, service output, and transport-neutral reply models unchanged. Add the behavior only in the NoneBot OneBot transport function by selecting send keyword arguments from the event type and reply source, then consuming the quote privilege on the first successfully rendered segment.

**Tech Stack:** Python 3.11, NoneBot2, OneBot V11, pytest, Ruff

---

## File Map

- Modify `tests/test_plugin_smoke.py`: add focused transport tests and update fake bot signatures to capture send keyword arguments.
- Modify `qq_rolebot/plugins/roleplay_chat.py`: apply quote and mention arguments to only the first rendered message for eligible group replies.
- Keep `qq_rolebot/service.py`, `qq_rolebot/policy.py`, and `qq_rolebot/outgoing.py` unchanged.

### Task 1: Add Group Quote Transport Behavior

**Files:**
- Modify: `tests/test_plugin_smoke.py:618`
- Modify: `tests/test_plugin_smoke.py:695`
- Modify: `qq_rolebot/plugins/roleplay_chat.py:398`

- [x] **Step 1: Update the voice test bot to capture keyword arguments**

Change the fake bot in `test_handle_message_sends_voice_record_when_rendered` so the test can prove the voice exception:

```python
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send(self, event, message, **kwargs):
        self.sent.append((message, kwargs))
```

Update its assertions to verify no quote options are passed:

```python
assert bot.sent
message, kwargs = bot.sent[0]
assert "record" in str(message)
assert kwargs == {}
```

- [x] **Step 2: Replace the existing multi-message transport test with focused group assertions**

Use a fake bot that records the rendered segment and keyword arguments:

```python
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send(self, event, message, **kwargs):
        self.sent.append((str(message), kwargs))
```

Create a group event and assert only the first of “text + image” carries the quote options:

```python
event = SimpleNamespace(message_type="group", group_id=20, user_id=99, message_id=12345)

await module.send_outgoing_reply(bot, event, reply)

assert len(bot.sent) == 2
assert "一切安好" in bot.sent[0][0]
assert bot.sent[0][1] == {"reply_message": True, "at_sender": True}
assert "image" in bot.sent[1][0]
assert bot.sent[1][1] == {}
```

- [x] **Step 3: Add failing tests for empty-first, repeat, and private behavior**

Add an empty-first group test proving the first renderable segment gets the quote:

```python
async def test_send_outgoing_reply_quotes_first_rendered_group_message(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message, **kwargs):
            self.sent.append((str(message), kwargs))

    reply = module.OutgoingReply(
        source="model",
        messages=[
            module.OutgoingMessage(kind="text", text=""),
            module.OutgoingMessage(kind="image", file="/opt/qq-rolebot/stickers/calm.webp"),
        ],
    )
    event = SimpleNamespace(message_type="group", group_id=20, user_id=99, message_id=12345)
    bot = FakeBot()

    await module.send_outgoing_reply(bot, event, reply)

    assert len(bot.sent) == 1
    assert "image" in bot.sent[0][0]
    assert bot.sent[0][1] == {"reply_message": True, "at_sender": True}
```

Add a repeat test:

```python
async def test_send_outgoing_reply_does_not_quote_group_repeat(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message, **kwargs):
            self.sent.append((str(message), kwargs))

    event = SimpleNamespace(message_type="group", group_id=20, user_id=99, message_id=12345)
    bot = FakeBot()

    await module.send_outgoing_reply(
        bot,
        event,
        module.OutgoingReply.text("复读内容", source="repeat"),
    )

    assert len(bot.sent) == 1
    assert bot.sent[0][1] == {}
```

Add a private test:

```python
async def test_send_outgoing_reply_does_not_quote_private_reply(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message, **kwargs):
            self.sent.append((str(message), kwargs))

    event = SimpleNamespace(message_type="private", user_id=99, message_id=12345)
    bot = FakeBot()

    await module.send_outgoing_reply(
        bot,
        event,
        module.OutgoingReply.text("私聊内容", source="model"),
    )

    assert len(bot.sent) == 1
    assert bot.sent[0][1] == {}
```

- [x] **Step 4: Run focused tests and verify RED**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest \
  tests/test_plugin_smoke.py::test_render_outgoing_reply_sends_text_and_image_separately \
  tests/test_plugin_smoke.py::test_send_outgoing_reply_quotes_first_rendered_group_message \
  tests/test_plugin_smoke.py::test_send_outgoing_reply_does_not_quote_group_repeat \
  tests/test_plugin_smoke.py::test_send_outgoing_reply_does_not_quote_private_reply \
  tests/test_plugin_smoke.py::test_handle_message_sends_voice_record_when_rendered -q
```

Expected: the eligible group-reply tests fail because current `send_outgoing_reply` passes no `reply_message` or `at_sender` keyword arguments; repeat, private, and voice assertions may already pass.

- [x] **Step 5: Implement minimal first-rendered-message quoting**

Replace `send_outgoing_reply` with:

```python
async def send_outgoing_reply(bot: Bot, event: MessageEvent, reply: OutgoingReply) -> None:
    quote_first_message = (
        getattr(event, "message_type", "") == "group" and reply.source != "repeat"
    )
    first_rendered_message = True
    for outgoing_message in reply.messages:
        segment = render_outgoing_message(outgoing_message)
        if segment is None:
            continue
        if quote_first_message and first_rendered_message:
            await bot.send(event, segment, reply_message=True, at_sender=True)
        else:
            await bot.send(event, segment)
        first_rendered_message = False
```

This leaves the TTS branch unchanged, so successful voice output remains an ordinary `bot.send(event, record)` call.

- [x] **Step 6: Run focused tests and verify GREEN**

Run the same focused pytest command from Step 4.

Expected: all five tests pass.

- [x] **Step 7: Run plugin and policy regression tests**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest \
  tests/test_plugin_smoke.py tests/test_policy.py tests/test_service.py -q
```

Expected: all tests pass, confirming the follow-up trigger remains unchanged and uses the same ordinary group reply transport path.

- [x] **Step 8: Run repository verification**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

Expected: Ruff exits 0, pytest reports zero failures, and `git diff --check` produces no output.

- [x] **Step 9: Review the final diff without committing**

Run:

```bash
git status --short --untracked-files=all
git diff -- qq_rolebot/plugins/roleplay_chat.py tests/test_plugin_smoke.py \
  docs/superpowers/specs/2026-07-10-group-quoted-replies-design.md \
  docs/superpowers/plans/2026-07-10-group-quoted-replies.md
```

Expected: only the quoted-reply implementation, tests, spec, and plan are present. Do not commit or push unless the user explicitly requests it.
