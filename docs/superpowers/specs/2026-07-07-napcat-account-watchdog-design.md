# NapCat Account Watchdog Design

## Goal

Add a server-side watchdog that detects when the QQ/NapCat account is likely offline and sends an
email alert to the administrator through QQ Mail SMTP. The watchdog must run independently from the
rolebot process so it can still alert when `qq-rolebot.service` is unhealthy.

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
recent NapCat logs for offline markers, stores the last status in `data/`, and sends email through
QQ Mail SMTP only on state transitions.

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

The body should include timestamp, host, failed checks, and a short recovery hint, but no secrets,
tokens, QR URLs, or message contents.

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

Default policy:

- Send an offline alert when status changes from `healthy` or unknown to `unhealthy`.
- Do not send repeated offline alerts while the status remains `unhealthy`.
- Send a recovery email when status changes from `unhealthy` to `healthy`.
- Continue logging every run to stdout/stderr so journald keeps an audit trail.

## Configuration

Document these server-only variables:

```dotenv
WATCHDOG_BOT_SERVICE=qq-rolebot.service
WATCHDOG_NAPCAT_SERVICE=napcat.service
WATCHDOG_HOST=127.0.0.1
WATCHDOG_PORT=8080
WATCHDOG_LOG_WINDOW_MINUTES=10
WATCHDOG_STATE_PATH=/opt/qq-rolebot/data/account_watchdog_state.json
WATCHDOG_SEND_RECOVERY=true

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=
```

The checked-in example must use placeholders only.

## Testing

Unit tests should cover:

- parsing environment values and defaults
- healthy and unhealthy check aggregation
- NapCat offline marker detection
- state-transition alert decisions
- email message construction without exposing secrets

The script should support dependency injection for command execution, clock, TCP connection checks,
and SMTP sender so tests do not require real systemd or real email.

Manual server verification should include:

1. Run the script once with services healthy and confirm no offline alert repeats.
2. Temporarily point `WATCHDOG_PORT` to an unused port and confirm one offline email is sent.
3. Restore the port and confirm one recovery email is sent.
4. Check `journalctl -u napcat-account-watchdog -n 80 --no-pager`.

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

Actual installation on the server can happen after the code is reviewed and committed.
