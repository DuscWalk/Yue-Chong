# NapCat Account Watchdog Design

## Goal

Add a server-side watchdog that detects when the QQ/NapCat account is likely offline and sends an
email alert to the administrator through QQ Mail SMTP. When a fresh login QR code is available or
can be generated, the alert should attach the QR image. If the administrator sees the alert after the
QR code has expired, replying to the alert should cause the server to generate and send a fresh QR
code. The watchdog must run independently from the rolebot process so it can still alert when
`qq-rolebot.service` is unhealthy.

## Constraints

- Production runs under `/opt/qq-rolebot` on Linux.
- The Python runtime is `/opt/miniconda3/envs/qq-rolebot`.
- `qq-rolebot.service` should keep listening on `127.0.0.1:8080`.
- NapCat runs as a separate systemd service, usually `napcat.service`.
- Real SMTP credentials, QQ tokens, QR URLs, and login material must stay server-only.
- CI/CD preserves `/opt/qq-rolebot/.env` and `/opt/qq-rolebot/data/`; implementation should also
  preserve `/opt/qq-rolebot/.watchdog.env`.

## Considered Approaches

### Recommended: Standalone Python Watchdog With systemd Timer

Create a small Python script that systemd runs every few minutes. It checks service health, scans
recent NapCat logs for offline markers, stores the last status in `data/`, sends email through QQ
Mail SMTP on state transitions, and polls QQ Mail IMAP for administrator replies that request a fresh
QR code.

This is the best fit because it stays independent from the bot, is easy to test locally, and uses
the existing Python environment.

### Alternative: Local mail/msmtp

Use system mail tooling and let the script call `mail` or `sendmail`. This keeps SMTP code out of
Python but adds more server package and MTA configuration work.

### Not Recommended: Bot-Process Monitor

Run the monitor inside `qq-rolebot.service`. This is easier to wire into existing config, but it
cannot alert when the bot process itself is down.

## Architecture

Add a script such as `scripts/napcat_account_watchdog.py`. The script is a one-shot command, not a
daemon. systemd owns scheduling through a service/timer pair:

```text
napcat-account-watchdog.timer
  -> napcat-account-watchdog.service
    -> /opt/miniconda3/envs/qq-rolebot/bin/python /opt/qq-rolebot/scripts/napcat_account_watchdog.py
```

The service loads a root-only environment file:

```text
/opt/qq-rolebot/.watchdog.env
```

The file should contain QQ Mail SMTP settings, alert recipients, service names, and optional timing
knobs. It must be mode `600` and must not be committed.

The watchdog remains a one-shot command even with reply handling. Each timer run performs these
steps:

1. Check the bot, NapCat, port, and recent logs.
2. If unhealthy, try to attach a fresh login QR code to the offline alert.
3. If reply handling is enabled, poll the mailbox for replies to recent watchdog alerts.
4. For an authorized reply, refresh the login QR code and send a new QR email.
5. Save status, alert history, QR history, and handled email UIDs to the state file.

## Detection Signals

The watchdog treats the account as unhealthy if any required signal fails:

- `systemctl is-active qq-rolebot.service` is not `active`.
- `systemctl is-active napcat.service` is not `active`.
- A TCP connection to `127.0.0.1:8080` fails.
- Recent NapCat logs contain offline markers such as `bot_offline`, `登录态已失效`, or equivalent
  account-expiry text.

The log window should be short, for example the last 10 minutes, so old offline logs do not keep
triggering alerts after recovery.

If the actual NapCat unit name differs, `WATCHDOG_NAPCAT_SERVICE` in `.watchdog.env` overrides it.

## Email Delivery

Use QQ Mail SMTP with SSL:

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=<sender>@qq.com
SMTP_PASSWORD=<qq-mail-smtp-authorization-code>
ALERT_EMAIL_FROM=<sender>@qq.com
ALERT_EMAIL_TO=<admin-address>
```

The SMTP password is the QQ Mail authorization code, not the QQ account password.

Alert subjects should be short and scannable:

- `[qq-rolebot] QQ account may be offline`
- `[qq-rolebot] QQ account recovered`

The body should include timestamp, host, failed checks, QR freshness, and a short recovery hint, but
no secrets, WebUI tokens, raw QR URLs, or message contents.

## State And Alert Policy

Store state in:

```text
/opt/qq-rolebot/data/account_watchdog_state.json
```

The state records:

- last known status: `healthy` or `unhealthy`
- last alert timestamp
- last recovery timestamp
- last failure reasons
- active QR request token
- last QR attachment timestamp and source path
- handled IMAP reply UIDs or message IDs

Default policy:

- Send an offline alert when status changes from `healthy` or unknown to `unhealthy`.
- Do not send repeated offline alerts while the status remains `unhealthy`.
- Send a recovery email when status changes from `unhealthy` to `healthy`.
- Continue logging every run to stdout/stderr so journald keeps an audit trail.

Reply-triggered QR emails are rate limited separately from offline alerts. The watchdog should not
send more than one QR refresh email within `WATCHDOG_QR_REPLY_COOLDOWN_SECONDS` unless the previous
send failed before reaching SMTP.

## QR Code Handling

NapCat commonly writes login QR images to a `cache/qrcode.png` file when QR login is active. The
exact path can differ by installation, so the implementation should make QR discovery configurable
instead of hard-coding one layout.

Configuration should support:

```dotenv
WATCHDOG_QR_PATH=
WATCHDOG_QR_GLOB=/root/Napcat/**/cache/qrcode.png
WATCHDOG_QR_MAX_AGE_SECONDS=120
WATCHDOG_QR_REFRESH_COMMAND="systemctl restart napcat.service"
WATCHDOG_QR_REFRESH_WAIT_SECONDS=15
```

Behavior:

- Prefer `WATCHDOG_QR_PATH` if set.
- Otherwise choose the newest file matching `WATCHDOG_QR_GLOB`.
- Treat the QR as fresh only when its modification time is within `WATCHDOG_QR_MAX_AGE_SECONDS`.
- When the QR is stale or missing and the account is unhealthy, run
  `WATCHDOG_QR_REFRESH_COMMAND`, wait up to `WATCHDOG_QR_REFRESH_WAIT_SECONDS`, then search again.
- If no fresh QR is available, send the offline alert without an attachment and include a short
  note that the administrator can reply to request a fresh QR.

The QR image is sensitive login material. It must never be copied into the repository, printed as
base64, or included in logs. Emails may attach the image as `napcat-login-qrcode.png`.

## Reply-By-Email Flow

Use QQ Mail IMAP over SSL to detect administrator replies:

```dotenv
WATCHDOG_REPLY_ENABLED=true
IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USER=<sender>@qq.com
IMAP_PASSWORD=<qq-mail-imap-authorization-code>
WATCHDOG_REPLY_ALLOWED_SENDERS=<admin-address>
WATCHDOG_REPLY_KEYWORDS=qr,qrcode,二维码,扫码,登录
WATCHDOG_QR_REPLY_COOLDOWN_SECONDS=60
```

QQ Mail usually uses the same authorization-code model for SMTP and IMAP, but the implementation
should keep the variables separate so the server can use different mailbox credentials if needed.

The offline alert subject should contain a random request token, for example:

```text
[qq-rolebot] QQ account may be offline [qr:8f2a1c]
```

A reply is accepted only when:

- the sender matches `WATCHDOG_REPLY_ALLOWED_SENDERS`
- the message is newer than the last handled reply UID or message timestamp
- the subject contains the active QR request token, or the body contains one of the configured reply
  keywords
- the account is currently unhealthy or the most recent QR request is still unresolved

After accepting a reply, the watchdog refreshes the QR, sends a new QR email, stores the handled
mail UID, and marks the message as seen if the IMAP account allows it. This lets an administrator
reply hours later and still receive a current QR code instead of relying on the expired attachment
from the original alert.

## Configuration

Document these server-only variables:

```dotenv
WATCHDOG_BOT_SERVICE=qq-rolebot.service
WATCHDOG_NAPCAT_SERVICE=napcat.service
WATCHDOG_HOST=127.0.0.1
WATCHDOG_PORT=8080
WATCHDOG_REQUIRE_ONEBOT_CONNECTION=true
WATCHDOG_LOG_WINDOW_MINUTES=10
WATCHDOG_STATE_PATH=/opt/qq-rolebot/data/account_watchdog_state.json
WATCHDOG_SEND_RECOVERY=true
WATCHDOG_QR_PATH=
WATCHDOG_QR_GLOB=/root/Napcat/**/cache/qrcode.png
WATCHDOG_QR_MAX_AGE_SECONDS=120
WATCHDOG_QR_REFRESH_COMMAND="systemctl restart napcat.service"
WATCHDOG_QR_REFRESH_WAIT_SECONDS=15
WATCHDOG_REPLY_ENABLED=true
WATCHDOG_REPLY_ALLOWED_SENDERS=
WATCHDOG_REPLY_KEYWORDS=qr,qrcode,二维码,扫码,登录
WATCHDOG_QR_REPLY_COOLDOWN_SECONDS=60

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=

IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USER=
IMAP_PASSWORD=
```

The checked-in example must use placeholders only.

## Testing

Unit tests should cover:

- parsing environment values and defaults
- healthy and unhealthy check aggregation
- NapCat offline marker detection
- state-transition alert decisions
- email message construction without exposing secrets
- QR file selection by explicit path, glob, freshness, and missing-file cases
- QR refresh command behavior without running a real restart in unit tests
- IMAP reply filtering by sender, token, keywords, UID, and cooldown

The script should support dependency injection for command execution, clock, TCP connection checks,
SMTP sender, IMAP reader, filesystem access, and QR refresh so tests do not require real systemd,
real email, or a real NapCat installation.

Manual server verification should include:

1. Run the script once with services healthy and confirm no offline alert repeats.
2. Temporarily point `WATCHDOG_PORT` to an unused port and confirm one offline email is sent.
3. Confirm the offline email attaches `napcat-login-qrcode.png` when a fresh QR exists.
4. Reply to the alert after the QR expires and confirm a new QR email is sent.
5. Restore the port and confirm one recovery email is sent.
6. Check `journalctl -u napcat-account-watchdog -n 80 --no-pager`.

## Deployment Notes

The deployment script already preserves `data/`, so the watchdog state file survives code
replacement. The implementation should extend deployment preservation to include `.watchdog.env`,
with mode `600` when restored. The file must be documented as server-only and must never be added to
git.

The first implementation should include:

- the Python watchdog script
- focused unit tests
- systemd service/timer examples in `docs/deployment.md`
- `.env.example` comments or a separate placeholder example without real credentials
- deployment preservation for `.watchdog.env`
- QR attachment and reply-by-email configuration notes

Actual installation on the server can happen after the code is reviewed and committed.
