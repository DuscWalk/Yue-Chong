from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import TypeAlias

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DATA_URL_RE = re.compile(r"data:[^\s,;]+(?:;base64)?,\S+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|token|password|secret)\s*[:=]\s*\S+"
)
_LONG_TOKEN_RE = re.compile(r"(?<![\w-])[A-Za-z0-9_+/=-]{48,}(?![\w-])")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExceptionAlertConfig:
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    smtp_user: str
    smtp_password: str
    sender: str
    recipients: tuple[str, ...]
    cooldown_seconds: int = 600


EmailSender: TypeAlias = Callable[[EmailMessage], None]


class ExceptionNotifier:
    def __init__(
        self,
        *,
        config: ExceptionAlertConfig,
        send_email: EmailSender | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._send_email = send_email or self._send_smtp_email
        self._now = now or time.time
        self._last_sent: dict[tuple[str, str], float] = {}

    async def notify(
        self,
        *,
        stage: str,
        error: BaseException,
        group_id: int = 0,
        user_id: int = 0,
        trace_id: str = "",
    ) -> bool:
        if not self._configured():
            return False
        key = (stage.strip() or "unknown", type(error).__name__)
        now = self._now()
        last_sent = self._last_sent.get(key)
        if last_sent is not None and now - last_sent < self.config.cooldown_seconds:
            return False
        self._last_sent[key] = now
        message = self._build_message(
            stage=key[0],
            error=error,
            group_id=group_id,
            user_id=user_id,
            trace_id=trace_id,
            now=now,
        )
        try:
            await asyncio.to_thread(self._send_email, message)
        except Exception:
            logger.exception("administrator exception alert failed")
        return True

    def _configured(self) -> bool:
        return bool(
            self.config.smtp_host
            and self.config.smtp_port
            and self.config.smtp_user
            and self.config.smtp_password
            and self.config.sender
            and self.config.recipients
        )

    def _build_message(
        self,
        *,
        stage: str,
        error: BaseException,
        group_id: int,
        user_id: int,
        trace_id: str,
        now: float,
    ) -> EmailMessage:
        exception_type = type(error).__name__
        details = _sanitize(_traceback_summary(error))
        body = "\n".join(
            (
                "qq-rolebot exception alert",
                f"timestamp={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}",
                f"stage={stage}",
                f"exception_type={exception_type}",
                f"group_id={group_id}",
                f"user_id={user_id}",
                f"trace_id={_safe_trace_id(trace_id)}",
                "details=",
                _sanitize(details),
            )
        )[:8000]
        message = EmailMessage()
        message["Subject"] = f"[qq-rolebot] {stage}: {exception_type}"
        message["From"] = self.config.sender
        message["To"] = ", ".join(self.config.recipients)
        message.set_content(body)
        return message

    def _send_smtp_email(self, message: EmailMessage) -> None:
        if self.config.smtp_ssl:
            with smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=20,
            ) as smtp:
                smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(message)
            return
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(self.config.smtp_user, self.config.smtp_password)
            smtp.send_message(message)


def _sanitize(value: str) -> str:
    sanitized = _DATA_URL_RE.sub("[data-redacted]", value)
    sanitized = _URL_RE.sub(_redact_url, sanitized)
    sanitized = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", sanitized)
    sanitized = _LONG_TOKEN_RE.sub("[opaque-redacted]", sanitized)
    return " ".join(sanitized.split())


def _traceback_summary(error: BaseException) -> str:
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return "traceback unavailable"
    return "\n".join(
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in frames[-12:]
    )


def _redact_url(match: re.Match[str]) -> str:
    return "[url-redacted]"


def _safe_trace_id(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value or "") else ""
