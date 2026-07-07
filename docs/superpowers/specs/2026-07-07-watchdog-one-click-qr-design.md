# Watchdog One-Click QR Design

## Goal

Replace the fragile `mailto:` QR button with a real HTTP button that works on mobile mail clients.
Clicking the button should ask the server to refresh the NapCat login QR code and email the newest
QR image to the configured administrator mailbox.

## Approved Approach

Use a small HTTP endpoint owned by the watchdog script, not the QQ rolebot chat service. The endpoint
validates an unguessable QR token from the email link, refreshes the QR through the existing
watchdog refresh command, and sends the QR by the existing QQ Mail SMTP path.

The button never displays the QR code in the browser. It only returns a short status page and sends
the QR image to the configured alert recipient.

## Scope

- Add optional config for a public click base URL, bind host, bind port, path prefix, and token TTL.
- Keep the existing reply-by-email flow as fallback.
- Prefer the HTTP link in HTML and plain-text email when a public base URL is configured.
- Fall back to the old `mailto:` button when no public base URL is configured.
- Add a script mode that serves the click endpoint as a small long-running HTTP service.
- Document a separate systemd service for the click endpoint.

## Security

- Use a longer default token for new watchdog incidents.
- Accept only the active token stored in the watchdog state file.
- Reject expired tokens using a token timestamp and configurable TTL.
- Rate-limit successful click requests with the existing QR reply cooldown.
- Do not print tokens, QR file paths, QR URLs, SMTP passwords, or authorization codes in logs.
- Do not expose the OneBot WebSocket or the chat bot FastAPI app publicly for this feature.

## Data Flow

1. A watchdog offline or fresh-QR email contains a link such as:

   ```text
   https://example.invalid/watchdog/qr/<token>
   ```

2. The administrator taps the button.
3. The watchdog HTTP service loads the state file and validates `<token>`.
4. If valid and not rate-limited, it restarts NapCat through the configured refresh command, waits
   for a fresh QR image, and sends a fresh QR email.
5. The browser shows a minimal success, throttled, expired, or invalid-token page.

## Testing

- Config parsing covers click URL, host, port, path prefix, and TTL.
- Email construction prefers the HTTP click link when configured and keeps secrets out of the body.
- Invalid or expired click tokens do not refresh NapCat and do not send email.
- A valid click token refreshes NapCat, sends one QR email, and records the click timestamp.
- A repeated valid click within cooldown returns a throttled result without sending another email.

