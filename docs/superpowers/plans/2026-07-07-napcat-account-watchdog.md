# NapCat Account Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a server-side NapCat account watchdog that sends QQ Mail alerts with
fresh login QR codes and can send a new QR code when the administrator replies by email.

**Architecture:** Add a standalone, importable Python script under `scripts/` with pure helper
functions for config, health checks, state transitions, QR selection, SMTP messages, and IMAP reply
filtering. systemd runs the script as a one-shot timer independent from `qq-rolebot.service`.
Deployment preserves `.watchdog.env`, installs the script through the normal archive deploy, and
adds server-side systemd units.

**Tech Stack:** Python 3.11 stdlib (`dataclasses`, `email`, `imaplib`, `json`, `pathlib`,
`secrets`, `smtplib`, `socket`, `subprocess`), pytest, ruff, systemd, QQ Mail SMTP/IMAP.

---

## File Map

- Create `scripts/napcat_account_watchdog.py`: one-shot watchdog command and importable pure helper
  functions.
- Create `tests/test_napcat_account_watchdog.py`: focused unit tests for config, health, state, QR,
  email, and reply filtering.
- Modify `scripts/deploy_server.sh`: preserve `.watchdog.env` during archive and git deployments.
- Modify `tests/test_deploy_script.py`: cover `.watchdog.env` preservation.
- Modify `.env.example`: add placeholder watchdog settings without real credentials.
- Modify `docs/deployment.md`: document QQ Mail setup, `.watchdog.env`, systemd units, QR refresh,
  reply-by-email, and manual verification.

## Task 1: Watchdog Pure Behavior Tests

**Files:**
- Create: `tests/test_napcat_account_watchdog.py`
- Create later: `scripts/napcat_account_watchdog.py`

- [ ] **Step 1: Write failing tests for config, health, and alert transitions**

```python
from pathlib import Path

from scripts.napcat_account_watchdog import (
    HealthReport,
    WatchdogConfig,
    decide_status_email,
    evaluate_health,
    load_config,
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


def test_decide_status_email_sends_offline_only_on_transition() -> None:
    report = HealthReport(status="unhealthy", reasons=["NapCat login requires QR/manual verification"])

    assert decide_status_email({}, report, send_recovery=True) == "offline"
    assert decide_status_email({"status": "healthy"}, report, send_recovery=True) == "offline"
    assert decide_status_email({"status": "unhealthy"}, report, send_recovery=True) is None
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: fails because `scripts.napcat_account_watchdog` does not exist.

- [ ] **Step 3: Implement minimal config, health, and state-transition helpers**

Create `scripts/napcat_account_watchdog.py` with dataclasses `WatchdogConfig` and `HealthReport`,
plus `load_config`, `evaluate_health`, and `decide_status_email`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: the new tests pass.

## Task 2: QR, Email, And Reply Tests

**Files:**
- Modify: `tests/test_napcat_account_watchdog.py`
- Modify: `scripts/napcat_account_watchdog.py`

- [ ] **Step 1: Write failing tests for QR discovery and email construction**

```python
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
```

- [ ] **Step 2: Write failing tests for reply filtering**

```python
def test_authorized_reply_matches_sender_and_token() -> None:
    config = WatchdogConfig(
        watchdog_reply_allowed_senders=["admin@example.com"],
        watchdog_reply_keywords=["qr", "二维码"],
    )
    reply = MailReply(uid="42", sender="admin@example.com", subject="Re: [qr:abc123]", body="")

    assert is_authorized_reply(config, reply, {"active_qr_token": "abc123", "handled_reply_uids": []})


def test_reply_rejects_duplicate_uid() -> None:
    config = WatchdogConfig(watchdog_reply_allowed_senders=["admin@example.com"])
    reply = MailReply(uid="42", sender="admin@example.com", subject="Re: [qr:abc123]", body="")

    assert not is_authorized_reply(
        config,
        reply,
        {"active_qr_token": "abc123", "handled_reply_uids": ["42"]},
    )
```

- [ ] **Step 3: Run tests to verify RED**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: fails because QR, email, and reply helpers are missing.

- [ ] **Step 4: Implement minimal QR, email, and reply helpers**

Add `find_fresh_qr`, `build_email_message`, `MailReply`, and `is_authorized_reply`.

- [ ] **Step 5: Run tests to verify GREEN**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: all watchdog unit tests pass.

## Task 3: Watchdog Main Command

**Files:**
- Modify: `scripts/napcat_account_watchdog.py`
- Modify: `tests/test_napcat_account_watchdog.py`

- [ ] **Step 1: Add failing tests for high-level run behavior**

Add tests that inject fake dependencies and assert:

- unhealthy status sends one offline email and writes state
- repeated unhealthy status does not resend
- authorized reply sends a QR refresh email and marks UID handled

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: fails because `run_watchdog` is missing.

- [ ] **Step 3: Implement `run_watchdog` and CLI `main`**

The command should:

- load config from `os.environ`
- check systemd services, TCP port, and recent journal text
- load and save JSON state
- generate an active QR token for offline alerts
- attach a fresh QR if available, refreshing through the configured command if needed
- poll IMAP only when reply handling is enabled
- send email only when SMTP settings are complete
- log operational messages without printing secrets or QR contents

- [ ] **Step 4: Run watchdog tests and full test suite**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q
```

Expected: all tests pass.

## Task 4: Deployment Preservation And Docs

**Files:**
- Modify: `scripts/deploy_server.sh`
- Modify: `tests/test_deploy_script.py`
- Modify: `.env.example`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Write failing deploy-script test**

Extend `tests/test_deploy_script.py` to assert `.watchdog.env` is copied with mode `600` and is
excluded from `git clean`.

- [ ] **Step 2: Run deploy-script test to verify RED**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_deploy_script.py -q
```

Expected: fails because `.watchdog.env` is not preserved.

- [ ] **Step 3: Update deploy script and docs**

Update `restore_runtime_files` to preserve `.watchdog.env`, add `git clean -e .watchdog.env`, and
document QQ Mail SMTP/IMAP plus systemd service/timer setup.

- [ ] **Step 4: Run docs/deploy tests**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_deploy_script.py -q
git diff --check
```

Expected: pass.

## Task 5: Local Verification And Commit

**Files:**
- All changed files from Tasks 1-4.

- [ ] **Step 1: Run full verification**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m ruff check .
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q
git diff --check
```

Expected: ruff passes, pytest reports all tests passing, diff check exits 0.

- [ ] **Step 2: Commit implementation**

Run:

```powershell
git status --short --untracked-files=all
git add scripts/napcat_account_watchdog.py tests/test_napcat_account_watchdog.py scripts/deploy_server.sh tests/test_deploy_script.py .env.example docs/deployment.md
git commit -m "feat: add napcat account watchdog"
```

## Task 6: Server Deployment

**Files:**
- Server-only: `/opt/qq-rolebot/.watchdog.env`
- Server-only: `/etc/systemd/system/napcat-account-watchdog.service`
- Server-only: `/etc/systemd/system/napcat-account-watchdog.timer`

- [ ] **Step 1: Create local source archive**

Run:

```powershell
git archive --format=tar.gz -o qq-rolebot-watchdog.tar.gz HEAD
```

- [ ] **Step 2: Upload and run deployment script**

Upload the archive and `scripts/deploy_server.sh` to `/tmp`, then run:

```bash
bash /tmp/qq-rolebot-deploy.sh /tmp/qq-rolebot-watchdog.tar.gz master "$(git rev-parse HEAD)"
```

- [ ] **Step 3: Create `.watchdog.env` with server-only secrets**

Use QQ Mail SMTP/IMAP authorization codes. Do not print the file contents in logs or commit them.
Set mode `600`.

- [ ] **Step 4: Install and enable systemd units**

Create `napcat-account-watchdog.service` and `napcat-account-watchdog.timer`, disable the old
`napcat-watchdog.timer`, then run `systemctl daemon-reload` and enable/start the new timer.

- [ ] **Step 5: Verify server behavior**

Run:

```bash
systemctl status qq-rolebot --no-pager -l
systemctl status napcat --no-pager -l
systemctl status napcat-account-watchdog.timer --no-pager -l
journalctl -u napcat-account-watchdog -n 80 --no-pager -l
```

Expected: bot and NapCat are active, watchdog timer is waiting, one manual run exits 0.

## Self-Review

- Spec coverage: The plan covers independent watchdog process, QQ Mail SMTP, IMAP reply handling,
  QR attachment and refresh, `.watchdog.env` preservation, state file, tests, docs, and server
  systemd deployment.
- Placeholder scan: No `TBD`, `TODO`, or open-ended implementation placeholders remain.
- Type consistency: The planned helper names are consistent across tests and implementation:
  `WatchdogConfig`, `HealthReport`, `MailReply`, `load_config`, `evaluate_health`,
  `decide_status_email`, `find_fresh_qr`, `build_email_message`, `is_authorized_reply`, and
  `run_watchdog`.
