# Message Segment And Error Alert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop unsupported message placeholders and runtime exception text from reaching chats, while sending deduplicated sanitized administrator email alerts.

**Architecture:** Unknown incoming OneBot segments are omitted from the text summary, so they cannot become repeatable bot text. A small async SMTP notifier is configured from the existing mail variables and called by the plugin's outer message boundary. The boundary catches parsing, service, voice, rendering, and OneBot send failures, logs them, sends no error reply, and never lets notifier failure escape.

**Tech Stack:** Python 3.11, NoneBot2/OneBot V11, `email.message.EmailMessage`, `smtplib`, `asyncio.to_thread`, pytest, pytest-asyncio, Ruff.

---

### Task 1: Ignore Unsupported Incoming Segments

**Files:**
- Modify: `qq_rolebot/message_segments.py`
- Modify: `tests/test_message_segments.py`
- Modify: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing parser tests**

Add tests proving that a `json` segment is omitted from `summarize_segments`, and that a message containing only that segment produces no incoming message through `build_incoming_message`.

```python
def test_summarize_segments_omits_unknown_segments() -> None:
    message = [segment("text", text="正常文本"), segment("json", data="{}")]

    assert message_segments.summarize_segments(message) == "正常文本"


def test_unknown_only_message_is_not_buildable() -> None:
    event = SimpleNamespace(
        message=[segment("json", data="{}")],
        message_type="group",
        group_id=20,
        user_id=10,
        time=100,
        sender=SimpleNamespace(card="", nickname="user"),
        to_me=False,
    )

    assert roleplay_chat.build_incoming_message(event, bot_id=10001) is None
```

- [ ] **Step 2: Run test to verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_message_segments.py tests/test_plugin_smoke.py
```

Expected: the existing summary still contains `[unsupported segment: json]`.

- [ ] **Step 3: Implement omission**

Remove the fallback placeholder append from `summarize_segments`; unknown segments contribute nothing. Keep all supported segment branches unchanged.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_message_segments.py tests/test_plugin_smoke.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/message_segments.py tests/test_message_segments.py tests/test_plugin_smoke.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/message_segments.py tests/test_message_segments.py tests/test_plugin_smoke.py
git commit -m "fix: ignore unsupported incoming segments"
```

### Task 2: Add Sanitized Exception Notifier

**Files:**
- Create: `qq_rolebot/exception_notifier.py`
- Modify: `qq_rolebot/config.py`
- Modify: `tests/test_config.py`
- Create: `tests/test_exception_notifier.py`

- [ ] **Step 1: Write failing notifier and config tests**

Test a redacted email, cooldown deduplication, empty-recipient disablement, SMTP failure isolation, and parsing/validation of `SMTP_*`, `ALERT_EMAIL_*`, and positive `EXCEPTION_ALERT_COOLDOWN_SECONDS`.

```python
@pytest.mark.asyncio
async def test_notifier_sends_redacted_email_once() -> None:
    sent = []
    notifier = ExceptionNotifier(
        config=ExceptionAlertConfig(
            smtp_host="smtp.test",
            smtp_port=465,
            smtp_ssl=True,
            smtp_user="bot@test",
            smtp_password="mail-secret",
            sender="bot@test",
            recipients=("admin@test",),
            cooldown_seconds=600,
        ),
        send_email=lambda message: sent.append(message),
        now=lambda: 100,
    )

    await notifier.notify(
        stage="message_handler",
        error=ValueError("request https://private.test/path?token=secret"),
        group_id=20,
        user_id=10,
    )

    body = sent[0].get_content()
    assert "private.test/path" not in body
    assert "token=secret" not in body
    assert "mail-secret" not in body
    assert "ValueError" in body
```

- [ ] **Step 2: Run test to verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_exception_notifier.py tests/test_config.py
```

Expected: import failure because the notifier and new settings do not exist.

- [ ] **Step 3: Implement notifier and settings**

Add immutable `ExceptionAlertConfig`, an injectable `ExceptionNotifier`, and a default SMTP sender. Use `asyncio.to_thread` for SMTP. Build a bounded plain-text `EmailMessage`; redact HTTP query strings, data URLs, authorization/password-like assignments, and long opaque values. Key cooldown by stage and exception class. Add the matching Settings fields and parse the existing mail variables plus `EXCEPTION_ALERT_COOLDOWN_SECONDS=600`.

- [ ] **Step 4: Update environment and run tests**

Add the cooldown variable to `.env.example` beside the existing SMTP block.

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_exception_notifier.py tests/test_config.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/exception_notifier.py qq_rolebot/config.py tests/test_exception_notifier.py tests/test_config.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/exception_notifier.py qq_rolebot/config.py tests/test_exception_notifier.py tests/test_config.py .env.example
git commit -m "feat: add sanitized exception email alerts"
```

### Task 3: Guard Plugin Processing And Sending

**Files:**
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Modify: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing boundary tests**

Add tests with fake service, notifier, and bot objects proving that an exception from service handling invokes the notifier and results in no `bot.send`, an exception from a later outgoing segment stops remaining sends without an error string, and an unknown outgoing kind returns no OneBot segment.

- [ ] **Step 2: Run test to verify failure**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_plugin_smoke.py
```

Expected: the current handler lets service/send exceptions escape and has no notifier injection.

- [ ] **Step 3: Implement the boundary**

Construct `exception_notifier` from Settings. Refactor the locked handler into a guarded operation that catches `Exception`, logs a stable `message_handler` stage, calls `await exception_notifier.notify(...)`, and returns without chat output. Render all valid outgoing segments before the first send; skip invalid kinds with a warning. Stop the send loop at the first OneBot exception. Do not include incoming text or exception text in the chat response.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q tests/test_plugin_smoke.py tests/test_message_segments.py
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check qq_rolebot/plugins/roleplay_chat.py tests/test_plugin_smoke.py
```

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/plugins/roleplay_chat.py tests/test_plugin_smoke.py
git commit -m "fix: suppress chat errors and alert administrators"
```

### Task 4: Document Mail Alerts And Validate Regression Surface

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `tests/test_service.py` only if the boundary changes its tested contract

- [ ] **Step 1: Document configuration and behavior**

State that `ALERT_EMAIL_TO` enables administrator alerts, SMTP credentials stay server-only, duplicate alerts are cooldown-limited, exceptions never become chat messages, and unknown incoming OneBot segments are ignored.

- [ ] **Step 2: Run full local verification**

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

- [ ] **Step 3: Inspect repository hygiene**

```bash
git status --short --untracked-files=all
rg -n "SMTP_PASSWORD=.+[^.]|api_key\s*=\s*['\"][^'\"]+" .env.example README.md docs qq_rolebot tests scripts
```

Review matches and ensure no real credentials, mail bodies, trace files, or server artifacts are staged.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md docs/deployment.md
git commit -m "docs: document bot exception alerts"
```

### Task 5: Deploy And Verify Production Behavior

**Files:**
- No server-only files are committed.

- [ ] **Step 1: Confirm production mail variables without printing values**

Check only whether `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_FROM`, and `ALERT_EMAIL_TO` are configured in `/opt/qq-rolebot/.env`. Do not display values.

- [ ] **Step 2: Push and wait for CI deployment**

Use the existing `master` workflow only after local tests pass. Wait for the new files to arrive and verify `qq-rolebot.service` is active and listening on `127.0.0.1:8080`.

- [ ] **Step 3: Verify unsupported segment behavior**

Use a controlled parser/repeat test or inspect a real event trace. Confirm no `[unsupported segment: json]` is emitted as bot text and no outgoing message uses a `json` segment.

- [ ] **Step 4: Verify exception suppression and email configuration**

Do not inject a deliberate exception into a production group. Inspect service logs and notifier configuration; if the user separately authorizes a controlled failure outside a group, run it and verify an administrator email without exposing its contents.
