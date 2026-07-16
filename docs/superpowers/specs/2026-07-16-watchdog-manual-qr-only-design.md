# Watchdog Manual QR Email Only Design

## Goal

Stop the NapCat account watchdog from sending proactive email alerts while preserving the
administrator's existing reply-by-email flow for requesting a fresh login QR code.

The watchdog must continue health checks, state persistence, logging, and QR refresh handling. Only
email delivery policy changes.

## Current Behavior

`run_watchdog` sends an offline email when health changes to `unhealthy`. It sends a recovery email
when health changes back to `healthy` and `WATCHDOG_SEND_RECOVERY` is enabled. Authorized IMAP
replies can independently refresh NapCat and send a fresh QR email.

`WATCHDOG_SEND_RECOVERY` does not suppress offline alerts. Clearing `ALERT_EMAIL_TO` would suppress
all emails, including reply-triggered QR responses, so it cannot implement the requested policy.

## Selected Approach

Add a `WATCHDOG_SEND_OFFLINE` boolean configuration field with a backwards-compatible default of
`true`. The offline transition branch will send email only when this flag is enabled. The server
configuration will set both:

```dotenv
WATCHDOG_SEND_OFFLINE=false
WATCHDOG_SEND_RECOVERY=false
```

The server will keep `WATCHDOG_REPLY_ENABLED=true`, the configured IMAP credentials, and the
authorized sender list unchanged. The reply branch will continue to use the existing SMTP
configuration and QR refresh command.

To enforce the requested reply-only trigger, the optional `napcat-qr-click.service` will be stopped
and disabled on the server. The regular `napcat-account-watchdog.timer` remains enabled so health
state and reply polling continue.

## Data Flow

1. The timer runs the watchdog and evaluates bot, NapCat, TCP, OneBot, and recent-log health.
2. The watchdog records status and failure reasons regardless of email settings.
3. Offline and recovery email branches are skipped when their respective flags are `false`.
4. The watchdog polls unread IMAP messages when reply handling is enabled.
5. An authorized reply from the configured sender containing the existing QR keywords refreshes
   NapCat, finds the newest QR image, and sends one QR email subject to the existing cooldown.
6. State records handled message UIDs and timestamps without storing credentials or QR contents.

## Error Handling And Security

- SMTP and IMAP credentials remain in the server-only `.watchdog.env`.
- Health failures are still visible in watchdog journald output and the state file.
- A failed QR refresh or missing QR image produces a reply email without an attachment, matching the
  existing fallback behavior.
- Invalid, unauthorized, duplicate, or cooldown-limited replies do not send email.
- No QR image, token, password, or mail credential is added to the repository or logs.

## Tests And Verification

Add focused tests covering:

- parsing `WATCHDOG_SEND_OFFLINE` and its default;
- no offline email when the flag is disabled;
- no recovery email when recovery sending is disabled;
- reply-triggered QR email still being sent with offline and recovery alerts disabled;
- the existing QR cooldown and sender authorization behavior remaining intact.

Run the repository's Ruff, full pytest suite, and `git diff --check`. On the server, verify the
effective redacted configuration, timer/service status, a dry watchdog run, and recent journald
output without printing secrets or QR material.
