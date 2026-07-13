from __future__ import annotations

from email.message import EmailMessage

import pytest

from qq_rolebot.exception_notifier import ExceptionAlertConfig, ExceptionNotifier


def alert_config(**overrides) -> ExceptionAlertConfig:
    values = {
        "smtp_host": "smtp.test",
        "smtp_port": 465,
        "smtp_ssl": True,
        "smtp_user": "bot@test",
        "smtp_password": "mail-secret",
        "sender": "bot@test",
        "recipients": ("admin@test",),
        "cooldown_seconds": 600,
    }
    values.update(overrides)
    return ExceptionAlertConfig(**values)


@pytest.mark.asyncio
async def test_notifier_sends_redacted_email_once() -> None:
    sent: list[EmailMessage] = []
    notifier = ExceptionNotifier(
        config=alert_config(),
        send_email=lambda message: sent.append(message),
        now=lambda: 100,
    )

    await notifier.notify(
        stage="message_handler",
        error=ValueError("request https://private.test/path?token=secret"),
        group_id=20,
        user_id=10,
    )
    await notifier.notify(
        stage="message_handler",
        error=ValueError("same failure"),
        group_id=20,
        user_id=10,
    )

    assert len(sent) == 1
    message = sent[0]
    body = message.get_content()
    assert message["From"] == "bot@test"
    assert message["To"] == "admin@test"
    assert "private.test/path" not in body
    assert "token=secret" not in body
    assert "mail-secret" not in body
    assert "ValueError" in body
    assert "group_id=20" in body
    assert "user_id=10" in body


@pytest.mark.asyncio
async def test_notifier_allows_different_stage_during_same_cooldown() -> None:
    sent: list[EmailMessage] = []
    notifier = ExceptionNotifier(
        config=alert_config(),
        send_email=lambda message: sent.append(message),
        now=lambda: 100,
    )

    await notifier.notify(stage="message_handler", error=ValueError("one"))
    await notifier.notify(stage="outgoing_send", error=ValueError("two"))

    assert len(sent) == 2


@pytest.mark.asyncio
async def test_notifier_does_not_include_arbitrary_exception_message() -> None:
    sent: list[EmailMessage] = []
    notifier = ExceptionNotifier(
        config=alert_config(),
        send_email=lambda message: sent.append(message),
    )

    await notifier.notify(
        stage="message_handler",
        error=ValueError("user wrote a private sentence that must not leave the chat"),
    )

    body = sent[0].get_content()
    assert "private sentence" not in body
    assert "ValueError" in body


@pytest.mark.asyncio
async def test_notifier_swallows_smtp_failure_and_does_not_retry_in_cooldown() -> None:
    calls = 0

    def fail(_: EmailMessage) -> None:
        nonlocal calls
        calls += 1
        raise OSError("smtp unavailable")

    notifier = ExceptionNotifier(
        config=alert_config(),
        send_email=fail,
        now=lambda: 100,
    )

    await notifier.notify(stage="message_handler", error=RuntimeError("failure"))
    await notifier.notify(stage="message_handler", error=RuntimeError("failure"))

    assert calls == 1


@pytest.mark.asyncio
async def test_notifier_does_nothing_without_recipients() -> None:
    sent: list[EmailMessage] = []
    notifier = ExceptionNotifier(
        config=alert_config(recipients=()),
        send_email=lambda message: sent.append(message),
    )

    await notifier.notify(stage="message_handler", error=RuntimeError("failure"))

    assert sent == []
