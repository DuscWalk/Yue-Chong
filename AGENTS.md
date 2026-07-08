# AGENTS.md

This file applies to the whole repository. It is for Codex or other agentic workers taking over
this project.

## Communication

- Talk with the user in Chinese.
- Keep status updates concise, but include enough operational detail for server work.
- Never print, commit, or preserve real passwords, API keys, QQ tokens, private SSH keys, or QR
  login URLs in repository files.
- If the user provides a secret for a one-off operation, use it only transiently and redact it in
  summaries.

## Project Snapshot

This is a NapCatQQ + NoneBot2 QQ roleplay bot.

- Runtime entry point: `bot.py`
- Main plugin: `qq_rolebot/plugins/roleplay_chat.py`
- Service orchestration: `qq_rolebot/service.py`
- Trigger and follow-up policy: `qq_rolebot/policy.py`
- Config parsing: `qq_rolebot/config.py`
- Persona files: `personas/default_dialect.yaml` and `personas/default.yaml`
- Deployment script: `scripts/deploy_server.sh`
- Production runbook: `docs/deployment.md`
- User-facing overview: `README.md`

The default persona variant is Wuhan-dialect Chongyue via `PERSONA_VARIANT=dialect`.

## Local Environment

- The local workspace is now Ubuntu/WSL under `/home/duscwalk/toys/qqBots`.
- Use the dedicated conda environment, not base Python. If conda is missing, install Miniconda
  under `~/miniconda3` and create a fresh Python 3.11 environment.
- Preferred local Python:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python
```

Useful commands:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

Use `rg` or `rg --files` for search. Use `apply_patch` for manual edits.

## Testing Expectations

- For code changes, add or update focused tests before implementation when practical.
- For docs-only changes, at least run `git diff --check`; run the full test suite when the docs
  change config examples, deployment scripts, or behavior descriptions.
- Before finalizing a code or deploy change, prefer:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
```

## Runtime Behavior To Preserve

- Private messages reply directly.
- Groups must be in `GROUP_WHITELIST` and enabled with `/bot on`.
- Direct `@` and replies to the bot should reply when the group is enabled.
- Follow-up replies are scoped to the same group and user after an addressed message, and still
  need to look addressed by question marks or `FOLLOWUP_TRIGGER_KEYWORDS`.
- There is currently no global text reply rate limiter in the service path.
- Random group replies are controlled by stored group probability, set with `/bot prob N`.
- Time questions can be direct tool replies.
- Tavily search only runs for private or explicitly addressed messages with current-information
  intent.
- TTS only runs for private or explicitly addressed messages containing `TTS_TRIGGER_KEYWORDS`;
  text fallback must remain available when TTS fails.

## Server And Deployment

Production is Linux-first.

Expected server layout:

```text
/opt/qq-rolebot
/opt/qq-rolebot/.env
/opt/qq-rolebot/data
/opt/miniconda3/envs/qq-rolebot
/root/Napcat
```

GitHub Actions deploys pushes to `master` by uploading a source archive to the server. The server
must not need to fetch from GitHub during deploy.

`scripts/deploy_server.sh` must continue to:

- operate only on `/opt/qq-rolebot`;
- preserve `.env`, `data/`, `voice_refs/`, `voice_cache/`, and `models/`;
- run server-side install, ruff, and pytest;
- restart `qq-rolebot.service`;
- wait for `127.0.0.1:8080` before reporting success.

Server-only artifacts must never be copied into git:

- `.env` and `.env.*` except `.env.example`
- SQLite databases
- NapCat/QQ account data
- QR code images and login URLs
- model weights, converted datasets, voice references, generated voice cache
- tarballs and deployment bundles

## NapCat Operations

When the bot does not reply, distinguish these layers:

1. `qq-rolebot.service` is the Python bot and should listen on `127.0.0.1:8080`.
2. `napcat.service` is the QQ/NapCat gateway.
3. QQ login state can expire even when both services are running.

Useful server checks:

```bash
systemctl status qq-rolebot --no-pager -l
journalctl -u qq-rolebot -n 120 --no-pager -l
ss -ltnp | grep ':8080'
systemctl status napcat --no-pager -l
journalctl -u napcat -n 160 --no-pager -l
```

If `qq-rolebot` is healthy but NapCat logs `bot_offline`, `登录态已失效`, or no OneBot WebSocket
events, the QQ account is not logged in.

For QR login recovery, prefer generating a fresh QR code immediately before asking the user to
scan it. Old QR codes expire quickly. Do not commit downloaded QR images such as
`napcat-qrcode.png`.

If NapCat is configured with password fallback and logs that captcha or SMS verification is
required, switch temporarily to QR login by disabling password fallback in `/root/Napcat/napcat.env`
after making a root-only backup.

## Security And Privacy

- Do not add real keys to `.env.example`, docs, tests, commits, or final answers.
- Redact API keys, QQ passwords, one-time URLs, WebUI tokens, and SSH material in copied logs.
- Avoid storing server passwords in files. One-off SSH diagnostics via transient scripts are
  acceptable only when explicitly requested by the user.

## Git Hygiene

- Do not revert user changes.
- Check `git status --short --untracked-files=all` before committing.
- Ignore unrelated dirty or untracked files unless they affect the task.
- Commit only the files relevant to the user request.
- Pushing to `master` triggers CI/CD and redeploys production; only push when the user asks or when
  the current task explicitly includes deployment.

## Documentation

- Keep `README.md` as the project overview and quick start.
- Keep `docs/deployment.md` as the production runbook.
- Keep persona behavior in `personas/*.yaml`, not hidden in code.
- When behavior changes, update tests and docs together.
