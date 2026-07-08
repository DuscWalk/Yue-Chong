#!/usr/bin/env python3
from __future__ import annotations

import email
import glob
import html
import http.server
import imaplib
import json
import os
import secrets
import shlex
import smtplib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

OFFLINE_LOG_MARKERS = (
    "bot_offline",
    "KickedOffLine",
    "登录态已失效",
    "Login Error",
)

MANUAL_LOGIN_LOG_MARKERS = (
    "请扫描下面的二维码",
    "二维码已保存",
    "qrcode",
    "sms-verify-login",
)


@dataclass(slots=True)
class WatchdogConfig:
    watchdog_bot_service: str = "qq-rolebot.service"
    watchdog_napcat_service: str = "napcat.service"
    watchdog_host: str = "127.0.0.1"
    watchdog_port: int = 8080
    watchdog_require_onebot_connection: bool = True
    watchdog_require_onebot_http_api: bool = False
    watchdog_onebot_http_api_base: str = ""
    watchdog_onebot_http_api_token: str = ""
    watchdog_onebot_http_api_timeout_seconds: int = 5
    watchdog_log_window_minutes: int = 10
    watchdog_state_path: str = "/opt/qq-rolebot/data/account_watchdog_state.json"
    watchdog_send_recovery: bool = True
    watchdog_qr_path: str = ""
    watchdog_qr_glob: str = "/root/Napcat/**/cache/qrcode.png"
    watchdog_qr_max_age_seconds: int = 120
    watchdog_qr_refresh_command: str = "systemctl restart napcat.service"
    watchdog_qr_refresh_wait_seconds: int = 15
    watchdog_reply_enabled: bool = False
    watchdog_reply_allowed_senders: list[str] = field(default_factory=list)
    watchdog_reply_keywords: list[str] = field(
        default_factory=lambda: ["qr", "qrcode", "二维码", "扫码", "登录"]
    )
    watchdog_click_public_base_url: str = ""
    watchdog_click_host: str = "127.0.0.1"
    watchdog_click_port: int = 18081
    watchdog_click_path_prefix: str = "/watchdog/qr"
    watchdog_click_token_ttl_seconds: int = 86400
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_ssl: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_from: str = ""
    alert_email_to: list[str] = field(default_factory=list)
    imap_host: str = "imap.qq.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    watchdog_qr_reply_cooldown_seconds: int = 60


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: str
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class MailReply:
    uid: str
    sender: str
    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class QrClickResult:
    status: str
    email_sent: bool


@dataclass(frozen=True, slots=True)
class WatchdogDependencies:
    service_is_active: Callable[[str], bool]
    tcp_connect: Callable[[str, int], bool]
    read_recent_logs: Callable[[WatchdogConfig], str]
    send_email: Callable[[WatchdogConfig, EmailMessage], None]
    read_replies: Callable[[WatchdogConfig], list[MailReply]]
    run_refresh_command: Callable[[WatchdogConfig], int]
    now: Callable[[], float]
    token_factory: Callable[[], str]
    sleep: Callable[[float], None]
    log: Callable[[str], None]
    onebot_connected: Callable[[WatchdogConfig], bool] = lambda config: True
    onebot_http_api_healthy: Callable[[WatchdogConfig], bool] = lambda config: True


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _normalize_path_prefix(value: str | None) -> str:
    prefix = (value or "/watchdog/qr").strip() or "/watchdog/qr"
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return prefix.rstrip("/") or "/watchdog/qr"


def load_config(env: Mapping[str, str]) -> WatchdogConfig:
    smtp_user = env.get("SMTP_USER", "")
    return WatchdogConfig(
        watchdog_bot_service=env.get("WATCHDOG_BOT_SERVICE", "qq-rolebot.service"),
        watchdog_napcat_service=env.get("WATCHDOG_NAPCAT_SERVICE", "napcat.service"),
        watchdog_host=env.get("WATCHDOG_HOST", "127.0.0.1"),
        watchdog_port=_int(env.get("WATCHDOG_PORT"), 8080),
        watchdog_require_onebot_connection=_bool(
            env.get("WATCHDOG_REQUIRE_ONEBOT_CONNECTION"),
            True,
        ),
        watchdog_require_onebot_http_api=_bool(
            env.get("WATCHDOG_REQUIRE_ONEBOT_HTTP_API"),
            False,
        ),
        watchdog_onebot_http_api_base=env.get("WATCHDOG_ONEBOT_HTTP_API_BASE", "").rstrip("/"),
        watchdog_onebot_http_api_token=env.get("WATCHDOG_ONEBOT_HTTP_API_TOKEN", ""),
        watchdog_onebot_http_api_timeout_seconds=_int(
            env.get("WATCHDOG_ONEBOT_HTTP_API_TIMEOUT_SECONDS"),
            5,
        ),
        watchdog_log_window_minutes=_int(env.get("WATCHDOG_LOG_WINDOW_MINUTES"), 10),
        watchdog_state_path=env.get(
            "WATCHDOG_STATE_PATH",
            "/opt/qq-rolebot/data/account_watchdog_state.json",
        ),
        watchdog_send_recovery=_bool(env.get("WATCHDOG_SEND_RECOVERY"), True),
        watchdog_qr_path=env.get("WATCHDOG_QR_PATH", ""),
        watchdog_qr_glob=env.get("WATCHDOG_QR_GLOB", "/root/Napcat/**/cache/qrcode.png"),
        watchdog_qr_max_age_seconds=_int(env.get("WATCHDOG_QR_MAX_AGE_SECONDS"), 120),
        watchdog_qr_refresh_command=env.get(
            "WATCHDOG_QR_REFRESH_COMMAND",
            "systemctl restart napcat.service",
        ),
        watchdog_qr_refresh_wait_seconds=_int(env.get("WATCHDOG_QR_REFRESH_WAIT_SECONDS"), 15),
        watchdog_reply_enabled=_bool(env.get("WATCHDOG_REPLY_ENABLED"), False),
        watchdog_reply_allowed_senders=_csv(env.get("WATCHDOG_REPLY_ALLOWED_SENDERS")),
        watchdog_reply_keywords=_csv(env.get("WATCHDOG_REPLY_KEYWORDS"))
        or ["qr", "qrcode", "二维码", "扫码", "登录"],
        watchdog_click_public_base_url=env.get("WATCHDOG_CLICK_PUBLIC_BASE_URL", ""),
        watchdog_click_host=env.get("WATCHDOG_CLICK_HOST", "127.0.0.1"),
        watchdog_click_port=_int(env.get("WATCHDOG_CLICK_PORT"), 18081),
        watchdog_click_path_prefix=_normalize_path_prefix(
            env.get("WATCHDOG_CLICK_PATH_PREFIX", "/watchdog/qr")
        ),
        watchdog_click_token_ttl_seconds=_int(
            env.get("WATCHDOG_CLICK_TOKEN_TTL_SECONDS"),
            86400,
        ),
        smtp_host=env.get("SMTP_HOST", "smtp.qq.com"),
        smtp_port=_int(env.get("SMTP_PORT"), 465),
        smtp_ssl=_bool(env.get("SMTP_SSL"), True),
        smtp_user=smtp_user,
        smtp_password=env.get("SMTP_PASSWORD", ""),
        alert_email_from=env.get("ALERT_EMAIL_FROM", smtp_user),
        alert_email_to=_csv(env.get("ALERT_EMAIL_TO")),
        imap_host=env.get("IMAP_HOST", "imap.qq.com"),
        imap_port=_int(env.get("IMAP_PORT"), 993),
        imap_user=env.get("IMAP_USER", smtp_user),
        imap_password=env.get("IMAP_PASSWORD", env.get("SMTP_PASSWORD", "")),
        watchdog_qr_reply_cooldown_seconds=_int(
            env.get("WATCHDOG_QR_REPLY_COOLDOWN_SECONDS"),
            60,
        ),
    )


def evaluate_health(
    config: WatchdogConfig,
    *,
    bot_active: bool,
    napcat_active: bool,
    tcp_ok: bool,
    onebot_connected: bool = True,
    onebot_http_api_healthy: bool = True,
    recent_logs: str,
) -> HealthReport:
    reasons: list[str] = []
    if not bot_active:
        reasons.append(f"{config.watchdog_bot_service} is not active")
    if not napcat_active:
        reasons.append(f"{config.watchdog_napcat_service} is not active")
    if not tcp_ok:
        reasons.append(f"{config.watchdog_host}:{config.watchdog_port} is not reachable")
    if config.watchdog_require_onebot_connection and not onebot_connected:
        reasons.append("OneBot reverse WebSocket is not connected")
    if config.watchdog_require_onebot_http_api and not onebot_http_api_healthy:
        reasons.append("OneBot HTTP API status check failed")
    if any(marker in recent_logs for marker in OFFLINE_LOG_MARKERS):
        reasons.append("NapCat offline/login-expired marker found")
    if any(marker in recent_logs for marker in MANUAL_LOGIN_LOG_MARKERS):
        reasons.append("NapCat login requires QR/manual verification")

    return HealthReport(status="unhealthy" if reasons else "healthy", reasons=reasons)


def decide_status_email(
    state: Mapping[str, object],
    report: HealthReport,
    *,
    send_recovery: bool,
) -> str | None:
    previous_status = state.get("status")
    if report.status == "unhealthy" and previous_status != "unhealthy":
        return "offline"
    if report.status == "healthy" and previous_status == "unhealthy" and send_recovery:
        return "recovery"
    return None


def _fresh_qr(path: Path, *, now: float, max_age_seconds: int) -> Path | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    if now - stat.st_mtime > max_age_seconds:
        return None
    if stat.st_size <= 0:
        return None
    return path


def find_fresh_qr(config: WatchdogConfig, *, now: float) -> Path | None:
    if config.watchdog_qr_path:
        explicit = _fresh_qr(
            Path(config.watchdog_qr_path),
            now=now,
            max_age_seconds=config.watchdog_qr_max_age_seconds,
        )
        if explicit is not None:
            return explicit

    candidates = [
        Path(path)
        for path in glob.glob(config.watchdog_qr_glob, recursive=True)
        if _fresh_qr(Path(path), now=now, max_age_seconds=config.watchdog_qr_max_age_seconds)
        is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_email_message(
    config: WatchdogConfig,
    *,
    subject: str,
    body: str,
    qr_path: Path | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = config.alert_email_from
    message["To"] = ", ".join(config.alert_email_to)
    message["Subject"] = subject
    message.set_content(_plain_body_with_qr_link(config, subject=subject, body=body))
    html_body = _html_body_with_qr_button(config, subject=subject, body=body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")

    if qr_path is not None:
        message.add_attachment(
            qr_path.read_bytes(),
            maintype="image",
            subtype="png",
            filename="napcat-login-qrcode.png",
        )
    return message


def _plain_body_with_qr_link(
    config: WatchdogConfig,
    *,
    subject: str,
    body: str,
) -> str:
    url = _qr_click_url(config, subject)
    if url is None:
        return body
    return "\n".join(
        [
            body.rstrip(),
            "",
            "Open this link to request a fresh QQ login QR code:",
            url,
            "",
            "If the link does not work, reply to this email with qr.",
        ]
    )


def _html_body_with_qr_button(
    config: WatchdogConfig,
    *,
    subject: str,
    body: str,
) -> str | None:
    url = _qr_click_url(config, subject)
    fallback = "If the button does not work, reply to this email with <code>qr</code>."
    if url is None:
        if "[qr:" not in subject or not config.alert_email_from:
            return None
        url = _qr_reply_mailto(config.alert_email_from, subject)
    escaped_body = html.escape(body).replace("\n", "<br>\n")
    return "\n".join(
        [
            "<!doctype html>",
            "<html>",
            "<body>",
            f"<p>{escaped_body}</p>",
            '<p><a style="display:inline-block;padding:10px 14px;'
            "background:#2563eb;color:#ffffff;text-decoration:none;"
            f'border-radius:6px" href="{html.escape(url, quote=True)}">'
            "获取新二维码</a></p>",
            f"<p>{fallback}</p>",
            "</body>",
            "</html>",
        ]
    )


def _qr_click_url(config: WatchdogConfig, subject: str) -> str | None:
    token = _qr_token_from_subject(subject)
    if not token or not config.watchdog_click_public_base_url:
        return None
    base_url = config.watchdog_click_public_base_url.rstrip("/")
    path_prefix = _normalize_path_prefix(config.watchdog_click_path_prefix)
    return f"{base_url}{path_prefix}/{quote(token, safe='')}"


def _qr_token_from_subject(subject: str) -> str:
    marker = "[qr:"
    start = subject.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = subject.find("]", start)
    if end < 0:
        return ""
    return subject[start:end].strip()


def qr_click_token_from_path(config: WatchdogConfig, request_target: str) -> str:
    path = urlsplit(request_target).path
    prefix = _normalize_path_prefix(config.watchdog_click_path_prefix)
    token_prefix = f"{prefix}/"
    if not path.startswith(token_prefix):
        return ""
    token = unquote(path[len(token_prefix) :])
    if not token or "/" in token:
        return ""
    return token


def _qr_reply_mailto(address: str, subject: str) -> str:
    reply_subject = f"Re: {subject}"
    reply_body = "qr\n"
    return (
        f"mailto:{quote(address, safe='@.+-_')}"
        f"?subject={quote(reply_subject, safe='')}"
        f"&body={quote(reply_body, safe='')}"
    )


def is_authorized_reply(
    config: WatchdogConfig,
    reply: MailReply,
    state: Mapping[str, object],
) -> bool:
    handled = {str(uid) for uid in state.get("handled_reply_uids", [])}
    if reply.uid in handled:
        return False

    allowed = {sender.lower() for sender in config.watchdog_reply_allowed_senders}
    if not allowed or reply.sender.lower() not in allowed:
        return False

    token = str(state.get("active_qr_token") or "")
    if token and f"[qr:{token}]" in reply.subject:
        return True

    searchable = f"{reply.subject}\n{reply.body}".lower()
    return any(keyword.lower() in searchable for keyword in config.watchdog_reply_keywords)


def load_state(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def email_configured(config: WatchdogConfig) -> bool:
    return bool(
        config.smtp_host
        and config.smtp_port
        and config.smtp_user
        and config.smtp_password
        and config.alert_email_from
        and config.alert_email_to
    )


def imap_configured(config: WatchdogConfig) -> bool:
    return bool(config.imap_host and config.imap_port and config.imap_user and config.imap_password)


def _send_if_configured(
    config: WatchdogConfig,
    deps: WatchdogDependencies,
    *,
    subject: str,
    body: str,
    qr_path: Path | None = None,
) -> bool:
    if not email_configured(config):
        deps.log("watchdog email is not configured; skipping alert")
        return False
    deps.send_email(
        config,
        build_email_message(config, subject=subject, body=body, qr_path=qr_path),
    )
    return True


def _fresh_qr_after_optional_refresh(
    config: WatchdogConfig,
    deps: WatchdogDependencies,
    *,
    force_refresh: bool,
) -> Path | None:
    qr = None if force_refresh else find_fresh_qr(config, now=deps.now())
    if qr is not None:
        return qr
    if config.watchdog_qr_refresh_command:
        deps.run_refresh_command(config)
        if config.watchdog_qr_refresh_wait_seconds > 0:
            deps.sleep(config.watchdog_qr_refresh_wait_seconds)
        qr = find_fresh_qr(config, now=deps.now())
    return qr


def _offline_body(report: HealthReport, qr_path: Path | None) -> str:
    lines = [
        "QQ/NapCat account may be offline.",
        "",
        "Reasons:",
        *(f"- {reason}" for reason in report.reasons),
        "",
    ]
    if qr_path is not None:
        lines.append("A fresh login QR code is attached as napcat-login-qrcode.png.")
    else:
        lines.append("No fresh QR code was available. Reply to this email to request a new one.")
    lines.append("Do not forward this email because the QR code grants login access.")
    return "\n".join(lines)


def _recovery_body() -> str:
    return "QQ/NapCat account appears healthy again. OneBot should be connected to qq-rolebot."


def _reply_qr_body(qr_path: Path | None) -> str:
    if qr_path is not None:
        return "Fresh QQ login QR code is attached as napcat-login-qrcode.png."
    return "The server tried to refresh the QR code, but no fresh QR image was available."


def handle_qr_click(
    config: WatchdogConfig,
    token: str,
    deps: WatchdogDependencies,
) -> QrClickResult:
    state_path = Path(config.watchdog_state_path)
    state = load_state(state_path)
    active_token = str(state.get("active_qr_token") or "")
    if not token or not active_token or not secrets.compare_digest(token, active_token):
        return QrClickResult(status="invalid", email_sent=False)

    now = int(deps.now())
    token_timestamp = int(
        state.get("active_qr_token_timestamp")
        or state.get("last_alert_timestamp")
        or 0
    )
    if (
        config.watchdog_click_token_ttl_seconds > 0
        and token_timestamp > 0
        and now - token_timestamp > config.watchdog_click_token_ttl_seconds
    ):
        return QrClickResult(status="expired", email_sent=False)

    last_click = int(state.get("last_qr_click_timestamp") or 0)
    if (
        last_click > 0
        and now - last_click < config.watchdog_qr_reply_cooldown_seconds
    ):
        return QrClickResult(status="throttled", email_sent=False)

    qr_path = _fresh_qr_after_optional_refresh(config, deps, force_refresh=True)
    sent = _send_if_configured(
        config,
        deps,
        subject=f"[qq-rolebot] Fresh QQ login QR [qr:{active_token}]",
        body=_reply_qr_body(qr_path),
        qr_path=qr_path,
    )
    if sent:
        state["last_qr_click_timestamp"] = now
        save_state(state_path, state)
        return QrClickResult(status="sent", email_sent=True)
    return QrClickResult(status="failed", email_sent=False)


def _qr_click_http_status(result: QrClickResult, *, path_matched: bool) -> int:
    if not path_matched:
        return 404
    return {
        "sent": 200,
        "throttled": 429,
        "expired": 410,
        "invalid": 403,
        "failed": 500,
    }.get(result.status, 500)


def _qr_click_response_html(result: QrClickResult, *, path_matched: bool) -> bytes:
    if not path_matched:
        title = "Link not found"
        message = "This watchdog link was not recognized."
    else:
        title, message = {
            "sent": (
                "QR email requested",
                "A fresh QQ login QR email has been sent to the administrator mailbox.",
            ),
            "throttled": (
                "Already requested",
                "A QR email was requested recently. Please check the mailbox first.",
            ),
            "expired": (
                "Link expired",
                "This watchdog link has expired. Reply to the alert email with qr.",
            ),
            "invalid": (
                "Invalid link",
                "This watchdog link is invalid or no longer active.",
            ),
        }.get(
            result.status,
            (
                "Request failed",
                "The server could not send the QR email. Please check watchdog logs.",
            ),
        )
    html_body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "</head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>"
        "</body></html>"
    )
    return html_body.encode("utf-8")


def serve_qr_click_webhook(config: WatchdogConfig, deps: WatchdogDependencies) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            token = qr_click_token_from_path(config, self.path)
            path_matched = bool(token)
            result = (
                handle_qr_click(config, token, deps)
                if path_matched
                else QrClickResult(status="invalid", email_sent=False)
            )
            payload = _qr_click_response_html(result, path_matched=path_matched)
            self.send_response(_qr_click_http_status(result, path_matched=path_matched))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            deps.log(f"watchdog click request from {self.client_address[0]}")

    address = (config.watchdog_click_host, config.watchdog_click_port)
    with http.server.ThreadingHTTPServer(address, Handler) as server:
        deps.log(
            "watchdog click server listening on "
            f"{config.watchdog_click_host}:{config.watchdog_click_port}"
        )
        server.serve_forever()


def run_watchdog(config: WatchdogConfig, deps: WatchdogDependencies) -> HealthReport:
    state_path = Path(config.watchdog_state_path)
    state = load_state(state_path)
    recent_logs = deps.read_recent_logs(config)
    report = evaluate_health(
        config,
        bot_active=deps.service_is_active(config.watchdog_bot_service),
        napcat_active=deps.service_is_active(config.watchdog_napcat_service),
        tcp_ok=deps.tcp_connect(config.watchdog_host, config.watchdog_port),
        onebot_connected=deps.onebot_connected(config),
        onebot_http_api_healthy=deps.onebot_http_api_healthy(config),
        recent_logs=recent_logs,
    )

    token = str(state.get("active_qr_token") or deps.token_factory())
    if report.status == "unhealthy":
        if config.watchdog_click_public_base_url and not state.get(
            "active_qr_token_timestamp"
        ):
            token = deps.token_factory()
        state["active_qr_token"] = token
        state.setdefault("active_qr_token_timestamp", int(deps.now()))

    email_kind = decide_status_email(
        state,
        report,
        send_recovery=config.watchdog_send_recovery,
    )
    if email_kind == "offline":
        qr_path = _fresh_qr_after_optional_refresh(config, deps, force_refresh=False)
        subject = f"[qq-rolebot] QQ account may be offline [qr:{token}]"
        if _send_if_configured(
            config,
            deps,
            subject=subject,
            body=_offline_body(report, qr_path),
            qr_path=qr_path,
        ):
            state["last_alert_timestamp"] = int(deps.now())
            if qr_path is not None:
                state["last_qr_path"] = str(qr_path)
                state["last_qr_timestamp"] = int(deps.now())
    elif email_kind == "recovery":
        if _send_if_configured(
            config,
            deps,
            subject="[qq-rolebot] QQ account recovered",
            body=_recovery_body(),
        ):
            state["last_recovery_timestamp"] = int(deps.now())

    handled = [str(uid) for uid in state.get("handled_reply_uids", [])]
    if config.watchdog_reply_enabled and imap_configured(config):
        for reply in deps.read_replies(config):
            if not is_authorized_reply(config, reply, state):
                continue
            last_qr_reply = int(state.get("last_qr_reply_timestamp") or 0)
            if deps.now() - last_qr_reply < config.watchdog_qr_reply_cooldown_seconds:
                continue
            qr_path = _fresh_qr_after_optional_refresh(config, deps, force_refresh=True)
            if _send_if_configured(
                config,
                deps,
                subject=f"[qq-rolebot] Fresh QQ login QR [qr:{token}]",
                body=_reply_qr_body(qr_path),
                qr_path=qr_path,
            ):
                handled.append(reply.uid)
                state["handled_reply_uids"] = sorted(set(handled))
                state["last_qr_reply_timestamp"] = int(deps.now())

    state["status"] = report.status
    state["last_failure_reasons"] = report.reasons
    state["last_checked_timestamp"] = int(deps.now())
    save_state(state_path, state)
    return report


def systemd_service_is_active(service: str) -> bool:
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def tcp_connect(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _endpoint_matches(endpoint: str, host: str, port: int) -> bool:
    endpoint = endpoint.strip("[]")
    if not endpoint.endswith(f":{port}"):
        return False
    if host in {"0.0.0.0", "::"}:
        return True
    return endpoint.startswith(f"{host}:") or endpoint.startswith(f"[{host}]:")


def onebot_connection_from_ss(output: str, host: str, port: int) -> bool:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "ESTAB":
            continue
        local_endpoint = parts[3]
        peer_endpoint = parts[4]
        if _endpoint_matches(local_endpoint, host, port) or _endpoint_matches(
            peer_endpoint,
            host,
            port,
        ):
            return True
    return False


def onebot_connected(config: WatchdogConfig) -> bool:
    result = subprocess.run(
        ["ss", "-H", "-tnp"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        errors="replace",
    )
    return onebot_connection_from_ss(
        result.stdout or "",
        config.watchdog_host,
        config.watchdog_port,
    )


def _onebot_api_post(config: WatchdogConfig, action: str) -> dict:
    base = config.watchdog_onebot_http_api_base.rstrip("/")
    if not base:
        raise ValueError("WATCHDOG_ONEBOT_HTTP_API_BASE is not configured")
    request = urllib.request.Request(
        f"{base}/{action.lstrip('/')}",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if config.watchdog_onebot_http_api_token:
        request.add_header("Authorization", f"Bearer {config.watchdog_onebot_http_api_token}")
    with urllib.request.urlopen(
        request,
        timeout=config.watchdog_onebot_http_api_timeout_seconds,
    ) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def onebot_http_api_healthy(config: WatchdogConfig) -> bool:
    if not config.watchdog_require_onebot_http_api:
        return True
    try:
        login_info = _onebot_api_post(config, "get_login_info")
        if int(login_info.get("retcode", -1)) != 0:
            return False
        status = _onebot_api_post(config, "get_status")
        if int(status.get("retcode", -1)) != 0:
            return False
    except (
        OSError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
        urllib.error.HTTPError,
    ):
        return False

    data = status.get("data")
    if isinstance(data, dict) and data.get("online") is False:
        return False
    return True


def read_recent_logs(config: WatchdogConfig) -> str:
    since = f"-{config.watchdog_log_window_minutes} minutes"
    chunks: list[str] = []
    for unit in (config.watchdog_napcat_service, config.watchdog_bot_service):
        result = subprocess.run(
            ["journalctl", "-u", unit, "--since", since, "--no-pager", "-l"],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            errors="replace",
        )
        chunks.append(result.stdout or "")
    return "\n".join(chunks)


def send_smtp_email(config: WatchdogConfig, message: EmailMessage) -> None:
    if config.smtp_ssl:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=20) as smtp:
            smtp.login(config.smtp_user, config.smtp_password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(config.smtp_user, config.smtp_password)
        smtp.send_message(message)


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    return str(make_header(decode_header(value)))


def _message_body(message: email.message.Message) -> str:
    if message.is_multipart():
        parts = []
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment" or content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(parts)
    payload = message.get_payload(decode=True)
    if payload is None:
        return str(message.get_payload() or "")
    return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


def read_imap_replies(config: WatchdogConfig) -> list[MailReply]:
    if not imap_configured(config):
        return []
    replies: list[MailReply] = []
    with imaplib.IMAP4_SSL(config.imap_host, config.imap_port) as mailbox:
        mailbox.login(config.imap_user, config.imap_password)
        mailbox.select("INBOX")
        status, data = mailbox.uid("search", None, "UNSEEN")
        if status != "OK" or not data:
            return []
        uids = data[0].split()[-20:]
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii", errors="replace")
            status, fetched = mailbox.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK":
                continue
            for item in fetched:
                if not isinstance(item, tuple):
                    continue
                parsed = email.message_from_bytes(item[1])
                sender = parseaddr(parsed.get("From", ""))[1]
                subject = _decode_header(parsed.get("Subject"))
                replies.append(
                    MailReply(
                        uid=uid,
                        sender=sender,
                        subject=subject,
                        body=_message_body(parsed),
                    )
                )
    return replies


def run_refresh_command(config: WatchdogConfig) -> int:
    if not config.watchdog_qr_refresh_command:
        return 0
    return subprocess.run(
        shlex.split(config.watchdog_qr_refresh_command),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode


def default_dependencies() -> WatchdogDependencies:
    return WatchdogDependencies(
        service_is_active=systemd_service_is_active,
        tcp_connect=tcp_connect,
        read_recent_logs=read_recent_logs,
        send_email=send_smtp_email,
        read_replies=read_imap_replies,
        run_refresh_command=run_refresh_command,
        now=time.time,
        token_factory=lambda: secrets.token_urlsafe(18),
        sleep=time.sleep,
        log=lambda message: print(message, file=sys.stderr),
        onebot_connected=onebot_connected,
        onebot_http_api_healthy=onebot_http_api_healthy,
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    config = load_config(os.environ)
    deps = default_dependencies()
    if argv == ["--serve-click-webhook"]:
        serve_qr_click_webhook(config, deps)
        return 0
    if argv:
        print("usage: napcat_account_watchdog.py [--serve-click-webhook]", file=sys.stderr)
        return 2

    report = run_watchdog(config, deps)
    print(f"status={report.status}")
    for reason in report.reasons:
        print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
