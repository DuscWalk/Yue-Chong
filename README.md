# QQ Rolebot

NapCatQQ + NoneBot2 的 QQ 日常聊天角色机器人。当前角色是《明日方舟》重岳，默认使用武汉话口吻的人设文件 `personas/default_dialect.yaml`，也保留普通话版本 `personas/default.yaml`。

## What It Does

- 通过 NapCatQQ 登录 QQ 小号，使用 OneBot V11 反向 WebSocket 接入 NoneBot。
- 支持群聊和私聊。私聊默认回复；群聊需要先由管理员开启。
- 群聊里被 `@`、被回复，或在短时间 follow-up 窗口内看起来是在对机器人说话时回复。
- 未明确叫到机器人时，可按低概率随机加入聊天；概率可按群设置。
- 群里出现连续重复消息时，可自动跟着复读一条；默认两名用户连续发同一文本即触发。
- 记住最近若干条上下文，并在回复前感知当前上海时间，避免晚上说“刚练完晨功”这类错位回答。
- 可查询当前时间，可在明确对机器人提问且出现搜索意图时调用 Tavily 搜索。
- 可识别图片、语音、文件等 OneBot 消息段的摘要，但不会编造看不见的细节。
- 可选 TTS 语音回复，支持 generic HTTP TTS、GPT-SoVITS、阿里云百炼 CosyVoice。
- 通过 GitHub Actions 推送到 `master` 后自动测试并部署到 Linux 服务器。

## Architecture

```text
QQ 小号
  -> NapCatQQ
  -> OneBot V11 reverse WebSocket ws://127.0.0.1:8080/onebot/v11/ws
  -> NoneBot / qq-rolebot.service
  -> ChatService
     -> SQLite context and group settings
     -> ToolRunner: time / Tavily search / persona source lookup
     -> OpenAI-compatible chat model
     -> optional TTS voice rendering
```

Large runtime files stay on the server only: model weights, voice references, generated voice cache files, container images, and QQ/NapCat account data.

## Development

Use conda rather than the base Python environment:

```bash
conda create -n qq-rolebot python=3.11 -y
conda activate qq-rolebot
python -m pip install -U pip
python -m pip install -e ".[dev]"
copy .env.example .env
python -m ruff check .
python -m pytest -q
```

Run locally:

```bash
python bot.py
```

NapCatQQ must point OneBot V11 reverse WebSocket to:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

Set the same token in NapCatQQ and `ONEBOT_ACCESS_TOKEN`.

## Core Configuration

Copy `.env.example` to `.env` and fill real values there. Never commit real API keys, QQ tokens, SSH keys, passwords, or account data.

Required basics:

- `BOT_HOST`, `BOT_PORT`: NoneBot listening address. The deployed default is `127.0.0.1:8080`.
- `ONEBOT_ACCESS_TOKEN`: must match NapCatQQ.
- `BOT_QQ`: QQ number of the bot account.
- `ADMIN_USERS`: comma-separated QQ IDs allowed to run `/bot` commands.
- `GROUP_WHITELIST`: comma-separated group IDs the bot may serve.
- `DATABASE_PATH`: SQLite file, usually `data/rolebot.sqlite3`.
- `MODEL_API_BASE`, `MODEL_API_KEY`, `MODEL_NAME`: OpenAI-compatible chat API settings.
- `MAX_OUTPUT_CHARS`: hard output length guard. Current persona also asks the model to stay around 20 Chinese characters.
- `DEFAULT_RANDOM_REPLY_PROBABILITY`: default random group reply probability for a new group setting. Existing groups can override it with `/bot prob`.
- `REPEAT_REPLY_ENABLED`: whether the bot joins consecutive repeated group messages.
- `REPEAT_REPLY_THRESHOLD`: how many consecutive matching messages trigger repeat reply. Minimum is `2`.

Persona selection:

- `PERSONA_VARIANT=dialect`: default, loads `personas/default_dialect.yaml`.
- `PERSONA_VARIANT=standard`: loads `personas/default.yaml`.
- `PERSONA_VARIANT=custom`: loads explicit `PERSONA_PATH`.

## Group Behavior

Groups are disabled by default even when in `GROUP_WHITELIST`. An admin must run `/bot on` in the group.

Reply rules:

- Private messages: reply directly.
- Group message from a non-whitelisted group: ignore.
- Group disabled or muted: ignore normal chat.
- `@` bot or reply to bot: reply when the group is enabled.
- Follow-up window: after a user addresses the bot, their later message in the same group can trigger if it contains a question mark or one of `FOLLOWUP_TRIGGER_KEYWORDS`.
- Repeat: if `REPEAT_REPLY_ENABLED=true`, the latest `REPEAT_REPLY_THRESHOLD` unaddressed group messages are identical, and at least two users joined the chain, reply with the same text.
- Keywords: if `KEYWORDS` appears in text, reply.
- Random: if group random probability passes, reply.

There is currently no global text reply rate limit in the service path. Use `/bot off`, `/bot mute`, or `/bot prob` to control group noise.

## Admin Commands

Only users in `ADMIN_USERS` can run these in group chat:

```text
/bot on
/bot off
/bot mute 10m
/bot prob 3
/bot clear
/bot status
/bot persona dialect
/bot persona standard
```

Notes:

- `/bot prob N` accepts `0` to `100` and controls random reply probability for that group.
- `/bot mute` accepts `s`, `m`, or `h`, such as `30s`, `10m`, `1h`.
- `/bot clear` clears recent context for that group.
- Persona switching is in memory for the running process; persistent default still comes from `.env`.

## Tools

Time:

- Enabled by `TOOLS_ENABLE_TIME=true`.
- Triggered by addressed questions containing words like `几点`, `时间`, `几号`, `星期几`.
- Returns a direct short time reply without calling the model.

Search:

- Requires `TAVILY_API_KEY`.
- Enabled by `TOOLS_ENABLE_SEARCH=true`.
- Triggered only when the message is private, `@` the bot, or replies to the bot, and contains current-information intent such as `今天`, `现在`, `最新`, `新闻`, `天气`, `价格`, `搜索`.
- `SEARCH_COOLDOWN_SECONDS=0` removes search cooldown; higher values limit searches per group/user scope.

Persona sources:

- Enabled by `TOOLS_ENABLE_PERSONA_SOURCES=true`.
- Uses `Sources` in the persona YAML, such as PRTS pages, to enrich role-related answers.
- It is context for the model, not a direct web-page dump.

## Voice Replies

Voice is optional and disabled by default:

```dotenv
TTS_ENABLED=false
```

Voice is attempted only when the message is private, `@` the bot, or replies to the bot, and contains one of `TTS_TRIGGER_KEYWORDS`.

Supported backends:

- `TTS_BACKEND=generic`: calls `POST {TTS_API_URL}/synthesize`.
- `TTS_BACKEND=gptsovits`: calls `POST {TTS_API_URL}/tts` and uses `TTS_REF_AUDIO_PATH`, `TTS_PROMPT_TEXT`, `TTS_PROMPT_LANG`, `TTS_TEXT_LANG`.
- `TTS_BACKEND=aliyun-cosyvoice`: calls Alibaba Cloud Model Studio / DashScope and uses `TTS_API_KEY`, `TTS_MODEL`, `TTS_AUDIO_FORMAT`, `TTS_SPEAKER`.

For the current Wuhan dialect persona, keep:

```dotenv
TTS_STYLE=沉稳自然，武汉话日常短句，连贯不逐字
TTS_DIALECT_HINT=武汉话
```

Generated audio is cached under `TTS_CACHE_DIR`. If TTS fails, the bot falls back to text.

## Deployment

Production deployment is Linux-first. Windows was useful for local testing, but server-side QQ/NapCat is more stable when kept on Linux with a managed process.

Pushes to `master` run GitHub Actions:

1. Install dependencies.
2. Run `ruff`.
3. Run `pytest`.
4. Create a source archive from the checked-out commit.
5. Upload the archive and `scripts/deploy_server.sh` to the server.
6. Deploy to `/opt/qq-rolebot`, preserving server-only runtime files.
7. Restart `qq-rolebot.service`.
8. Wait for `127.0.0.1:8080` to accept connections.

Required GitHub repository secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_PORT`
- `DEPLOY_SSH_KEY`

See [docs/deployment.md](docs/deployment.md) for server setup, NapCat configuration, TTS backend notes, CI/CD behavior, and troubleshooting.

## Troubleshooting Quick Checks

NapCat says `ECONNREFUSED 127.0.0.1:8080`:

```bash
systemctl status qq-rolebot --no-pager
journalctl -u qq-rolebot -n 120 --no-pager
ss -ltnp | grep ':8080'
```

Linux QQ/NapCat crashes with GPU errors:

```bash
systemctl list-units '*nap*'
journalctl -u napcat -n 120 --no-pager
```

Make sure the effective NapCat/QQ launcher uses the same idea as:

```bash
xvfb-run -a qq --no-sandbox --disable-gpu --disable-dev-shm-usage
```

Bot is too noisy:

```text
/bot prob 0
/bot mute 10m
/bot off
```

Bot does not reply in a group:

- Confirm the group ID is in `GROUP_WHITELIST`.
- Run `/bot status`.
- Run `/bot on` if disabled.
- Confirm the message is `@`/reply/follow-up/keyword/random-triggered.

Bot does not reply in private chat:

- Check whether NapCat is still logged in.
- Check `qq-rolebot.service` logs.
- Confirm model API settings are valid.
