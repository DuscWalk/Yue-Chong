from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.napcat_account_watchdog import (
    HealthReport,
    MailReply,
    WatchdogConfig,
    WatchdogDependencies,
    build_email_message,
    decide_status_email,
    evaluate_health,
    find_fresh_qr,
    is_authorized_reply,
    load_config,
    onebot_connection_from_ss,
    run_watchdog,
)


def test_load_config_uses_qq_mail_defaults() -> None:
    config = load_config(
        {
            "SMTP_USER": "sender@qq.com",
            "SMTP_PASSWORD": "smtp-code",
            "ALERT_EMAIL_TO": "admin@example.com",
        }
    )

    assert config.smtp_host == "smtp.qq.com"
    assert config.smtp_port == 465
    assert config.smtp_ssl is True
    assert config.imap_host == "imap.qq.com"
    assert config.watchdog_host == "127.0.0.1"
    assert config.watchdog_port == 8080
    assert config.alert_email_from == "sender@qq.com"
    assert config.alert_email_to == ["admin@example.com"]


def test_load_config_can_disable_onebot_connection_requirement() -> None:
    config = load_config({"WATCHDOG_REQUIRE_ONEBOT_CONNECTION": "false"})

    assert config.watchdog_require_onebot_connection is False


def test_evaluate_health_reports_each_failed_signal() -> None:
    config = WatchdogConfig()
    report = evaluate_health(
        config,
        bot_active=False,
        napcat_active=True,
        tcp_ok=False,
        recent_logs="Login Error,ErrType: 1 ErrCode: 3\n请扫描下面的二维码",
    )

    assert report.status == "unhealthy"
    assert "qq-rolebot.service is not active" in report.reasons
    assert "127.0.0.1:8080 is not reachable" in report.reasons
    assert "NapCat login requires QR/manual verification" in report.reasons


def test_evaluate_health_requires_onebot_connection() -> None:
    config = WatchdogConfig()
    report = evaluate_health(
        config,
        bot_active=True,
        napcat_active=True,
        tcp_ok=True,
        onebot_connected=False,
        recent_logs="",
    )

    assert report.status == "unhealthy"
    assert "OneBot reverse WebSocket is not connected" in report.reasons


def test_evaluate_health_can_ignore_onebot_connection() -> None:
    config = WatchdogConfig(watchdog_require_onebot_connection=False)
    report = evaluate_health(
        config,
        bot_active=True,
        napcat_active=True,
        tcp_ok=True,
        onebot_connected=False,
        recent_logs="",
    )

    assert report.status == "healthy"
    assert report.reasons == []


def test_onebot_connection_from_ss_detects_local_rolebot_connection() -> None:
    output = (
        "ESTAB 0 0 127.0.0.1:41980 127.0.0.1:8080 users:((\"qq\",pid=1,fd=1))\n"
    )

    assert onebot_connection_from_ss(output, "127.0.0.1", 8080) is True


def test_onebot_connection_from_ss_ignores_external_remote_port_8080() -> None:
    output = (
        "ESTAB 0 0 172.17.150.1:57704 120.241.130.195:8080 users:((\"qq\",pid=1,fd=1))\n"
    )

    assert onebot_connection_from_ss(output, "127.0.0.1", 8080) is False


def test_decide_status_email_sends_offline_only_on_transition() -> None:
    report = HealthReport(
        status="unhealthy",
        reasons=["NapCat login requires QR/manual verification"],
    )

    assert decide_status_email({}, report, send_recovery=True) == "offline"
    assert decide_status_email({"status": "healthy"}, report, send_recovery=True) == "offline"
    assert decide_status_email({"status": "unhealthy"}, report, send_recovery=True) is None


def test_find_fresh_qr_prefers_explicit_path(tmp_path: Path) -> None:
    qr = tmp_path / "qrcode.png"
    qr.write_bytes(b"png")
    config = WatchdogConfig(watchdog_qr_path=str(qr), watchdog_qr_max_age_seconds=120)

    found = find_fresh_qr(config, now=qr.stat().st_mtime + 10)

    assert found == qr


def test_build_email_attaches_qr_without_leaking_secret(tmp_path: Path) -> None:
    qr = tmp_path / "qrcode.png"
    qr.write_bytes(b"fake-png")
    config = WatchdogConfig(
        smtp_user="sender@qq.com",
        smtp_password="secret-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
    )

    message = build_email_message(
        config,
        subject="[qq-rolebot] QQ account may be offline [qr:abc123]",
        body="NapCat needs QR login.",
        qr_path=qr,
    )

    raw = message.as_string()
    assert "secret-code" not in raw
    assert "napcat-login-qrcode.png" in raw


def test_build_email_adds_mailto_button_for_qr_alert() -> None:
    config = WatchdogConfig(
        smtp_user="sender@qq.com",
        smtp_password="secret-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
    )

    message = build_email_message(
        config,
        subject="[qq-rolebot] QQ account may be offline [qr:abc123]",
        body="NapCat needs QR login.",
    )

    html_part = next(
        part for part in message.walk() if part.get_content_type() == "text/html"
    )
    html = html_part.get_content()
    assert "获取新二维码" in html
    assert "secret-code" not in html

    href_start = html.index('href="') + len('href="')
    href_end = html.index('"', href_start)
    parsed = urlparse(unescape(html[href_start:href_end]))
    query = parse_qs(parsed.query)

    assert parsed.scheme == "mailto"
    assert parsed.path == "sender@qq.com"
    assert query["subject"] == ["Re: [qq-rolebot] QQ account may be offline [qr:abc123]"]
    assert query["body"] == ["qr\n"]


def test_authorized_reply_matches_sender_and_token() -> None:
    config = WatchdogConfig(
        watchdog_reply_allowed_senders=["admin@example.com"],
        watchdog_reply_keywords=["qr", "二维码"],
    )
    reply = MailReply(uid="42", sender="admin@example.com", subject="Re: [qr:abc123]", body="")

    assert is_authorized_reply(
        config,
        reply,
        {"active_qr_token": "abc123", "handled_reply_uids": []},
    )


def test_reply_rejects_duplicate_uid() -> None:
    config = WatchdogConfig(watchdog_reply_allowed_senders=["admin@example.com"])
    reply = MailReply(uid="42", sender="admin@example.com", subject="Re: [qr:abc123]", body="")

    assert not is_authorized_reply(
        config,
        reply,
        {"active_qr_token": "abc123", "handled_reply_uids": ["42"]},
    )


def test_run_watchdog_sends_offline_email_once(tmp_path: Path) -> None:
    qr = tmp_path / "qrcode.png"
    qr.write_bytes(b"fake-png")
    sent = []
    config = WatchdogConfig(
        watchdog_state_path=str(tmp_path / "state.json"),
        watchdog_qr_path=str(qr),
        smtp_user="sender@qq.com",
        smtp_password="smtp-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
        imap_user="sender@qq.com",
        imap_password="imap-code",
    )
    deps = WatchdogDependencies(
        service_is_active=lambda service: service == "napcat.service",
        tcp_connect=lambda host, port: False,
        read_recent_logs=lambda cfg: "请扫描下面的二维码",
        send_email=lambda cfg, message: sent.append(message),
        read_replies=lambda cfg: [],
        run_refresh_command=lambda cfg: 0,
        now=lambda: qr.stat().st_mtime + 1,
        token_factory=lambda: "abc123",
        sleep=lambda seconds: None,
        log=lambda message: None,
    )

    first = run_watchdog(config, deps)
    second = run_watchdog(config, deps)

    assert first.status == "unhealthy"
    assert second.status == "unhealthy"
    assert len(sent) == 1
    assert "[qr:abc123]" in sent[0]["Subject"]


def test_run_watchdog_sends_recovery_email_after_unhealthy(tmp_path: Path) -> None:
    sent = []
    config = WatchdogConfig(
        watchdog_state_path=str(tmp_path / "state.json"),
        smtp_user="sender@qq.com",
        smtp_password="smtp-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
        imap_user="sender@qq.com",
        imap_password="imap-code",
    )
    unhealthy_deps = WatchdogDependencies(
        service_is_active=lambda service: False,
        tcp_connect=lambda host, port: False,
        read_recent_logs=lambda cfg: "",
        send_email=lambda cfg, message: sent.append(message),
        read_replies=lambda cfg: [],
        run_refresh_command=lambda cfg: 0,
        now=lambda: 100.0,
        token_factory=lambda: "abc123",
        sleep=lambda seconds: None,
        log=lambda message: None,
    )
    healthy_deps = WatchdogDependencies(
        service_is_active=lambda service: True,
        tcp_connect=lambda host, port: True,
        read_recent_logs=lambda cfg: "",
        send_email=lambda cfg, message: sent.append(message),
        read_replies=lambda cfg: [],
        run_refresh_command=lambda cfg: 0,
        now=lambda: 200.0,
        token_factory=lambda: "def456",
        sleep=lambda seconds: None,
        log=lambda message: None,
    )

    run_watchdog(config, unhealthy_deps)
    report = run_watchdog(config, healthy_deps)

    assert report.status == "healthy"
    assert len(sent) == 2
    assert sent[1]["Subject"] == "[qq-rolebot] QQ account recovered"


def test_run_watchdog_marks_missing_onebot_connection_unhealthy(tmp_path: Path) -> None:
    sent = []
    config = WatchdogConfig(
        watchdog_state_path=str(tmp_path / "state.json"),
        smtp_user="sender@qq.com",
        smtp_password="smtp-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
    )
    deps = WatchdogDependencies(
        service_is_active=lambda service: True,
        tcp_connect=lambda host, port: True,
        read_recent_logs=lambda cfg: "",
        send_email=lambda cfg, message: sent.append(message),
        read_replies=lambda cfg: [],
        run_refresh_command=lambda cfg: 0,
        now=lambda: 100.0,
        token_factory=lambda: "abc123",
        sleep=lambda seconds: None,
        log=lambda message: None,
        onebot_connected=lambda cfg: False,
    )

    report = run_watchdog(config, deps)

    assert report.status == "unhealthy"
    assert "OneBot reverse WebSocket is not connected" in report.reasons
    assert len(sent) == 1


def test_run_watchdog_reply_sends_fresh_qr_and_marks_uid(tmp_path: Path) -> None:
    qr = tmp_path / "qrcode.png"
    qr.write_bytes(b"fake-png")
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"status":"unhealthy","active_qr_token":"abc123","handled_reply_uids":[]}',
        encoding="utf-8",
    )
    sent = []
    refreshes = []
    config = WatchdogConfig(
        watchdog_state_path=str(state_path),
        watchdog_qr_path=str(qr),
        watchdog_reply_enabled=True,
        watchdog_reply_allowed_senders=["admin@example.com"],
        smtp_user="sender@qq.com",
        smtp_password="smtp-code",
        alert_email_from="sender@qq.com",
        alert_email_to=["admin@example.com"],
        imap_user="sender@qq.com",
        imap_password="imap-code",
    )
    reply = MailReply(uid="42", sender="admin@example.com", subject="Re: [qr:abc123]", body="")
    deps = WatchdogDependencies(
        service_is_active=lambda service: True,
        tcp_connect=lambda host, port: False,
        read_recent_logs=lambda cfg: "请扫描下面的二维码",
        send_email=lambda cfg, message: sent.append(message),
        read_replies=lambda cfg: [reply],
        run_refresh_command=lambda cfg: refreshes.append(cfg.watchdog_qr_refresh_command) or 0,
        now=lambda: qr.stat().st_mtime + 1,
        token_factory=lambda: "abc123",
        sleep=lambda seconds: None,
        log=lambda message: None,
    )

    run_watchdog(config, deps)

    assert refreshes == ["systemctl restart napcat.service"]
    assert len(sent) == 1
    assert sent[0]["Subject"] == "[qq-rolebot] Fresh QQ login QR [qr:abc123]"
    assert '"42"' in state_path.read_text(encoding="utf-8")
