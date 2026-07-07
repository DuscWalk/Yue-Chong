# Watchdog One-Click QR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mobile-friendly one-click QR refresh link to watchdog emails.

**Architecture:** Extend `scripts/napcat_account_watchdog.py` with pure click-token helpers and a
small stdlib HTTP server mode. Email rendering will prefer a configured public click URL and retain
the existing `mailto:` fallback. Server deployment will run the click endpoint as a separate systemd
service so the rolebot FastAPI/OneBot port stays private.

**Tech Stack:** Python 3.11 stdlib (`http.server`, `email`, `json`, `pathlib`, `secrets`,
`urllib.parse`), pytest, ruff, systemd.

---

## File Map

- Modify `scripts/napcat_account_watchdog.py`: click config, link rendering, token lifecycle, click
  request handling, and HTTP server mode.
- Modify `tests/test_napcat_account_watchdog.py`: config, email link, valid click, expired click,
  and cooldown tests.
- Modify `.env.example`: placeholder click endpoint settings.
- Modify `docs/deployment.md`: public URL, systemd service, security notes, and manual test steps.

## Task 1: Click Link Tests

- [ ] **Step 1: Add failing tests**

Add tests that assert:

- `load_config` parses `WATCHDOG_CLICK_PUBLIC_BASE_URL`, `WATCHDOG_CLICK_HOST`,
  `WATCHDOG_CLICK_PORT`, `WATCHDOG_CLICK_PATH_PREFIX`, and `WATCHDOG_CLICK_TOKEN_TTL_SECONDS`.
- `build_email_message` uses an HTTP(S) QR link instead of `mailto:` when a public base URL is set.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: tests fail because click config and HTTP link rendering do not exist yet.

- [ ] **Step 3: Implement the minimal config and link rendering**

Add config fields, URL construction helpers, and an HTTP-link branch in the HTML/plain email body.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: watchdog tests pass.

## Task 2: Click Request Tests

- [ ] **Step 1: Add failing tests**

Add tests for:

- invalid token returns `invalid` and sends no email
- expired token returns `expired` and sends no email
- valid token refreshes NapCat, sends a fresh QR email, and saves `last_qr_click_timestamp`
- valid token within cooldown returns `throttled` and sends no email

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: tests fail because click request handling does not exist yet.

- [ ] **Step 3: Implement click handling**

Add `QrClickResult`, `handle_qr_click`, token timestamp tracking, and token-safe response text.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_napcat_account_watchdog.py -q
```

Expected: watchdog tests pass.

## Task 3: HTTP Server Mode And Docs

- [ ] **Step 1: Add HTTP server mode**

Add `--serve-click-webhook` to run a `ThreadingHTTPServer` on the configured host and port. The
request logger must not print the tokenized path.

- [ ] **Step 2: Update docs and examples**

Document the systemd service, public base URL, and manual verification command.

- [ ] **Step 3: Run full verification**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m ruff check .
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q
git diff --check
```

Expected: all commands exit 0.

## Task 4: Deploy And Trial Email

- [ ] **Step 1: Commit implementation**

Commit only the one-click QR files.

- [ ] **Step 2: Deploy archive to the server**

Deploy through `scripts/deploy_server.sh`, preserving server-only `.watchdog.env`.

- [ ] **Step 3: Configure and start the click service**

Set the public base URL and start a new `napcat-qr-click.service`.

- [ ] **Step 4: Send a trial email**

Send one test watchdog email with a click token and verify the link can be opened from a phone.

## Self-Review

- Spec coverage: Config, email rendering, token validation, cooldown, HTTP service, docs, and server
  trial steps are covered.
- Placeholder scan: No placeholder implementation steps remain.
- Type consistency: Helper names are consistent across tasks: `QrClickResult`, `handle_qr_click`,
  and `--serve-click-webhook`.

