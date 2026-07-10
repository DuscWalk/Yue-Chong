# Deployment

This document is the production runbook for the QQ rolebot. The current production target is a Linux server, with Python running from a dedicated conda environment and NapCatQQ running as the QQ gateway.

Do not put secrets in this repository. Keep API keys, QQ login data, voice references, generated audio, model weights, and container images on the server only.

## Server Layout

Expected paths:

```text
/opt/qq-rolebot                         app code deployed by CI/CD
/opt/qq-rolebot/.env                    production secrets and runtime config
/opt/qq-rolebot/.watchdog.env           server-only QQ Mail watchdog config
/opt/qq-rolebot/data/rolebot.sqlite3    group settings and recent context
/opt/qq-rolebot/data/custom_faces.json  local custom-face registration cache
/opt/qq-rolebot/data/voice_cache        generated outgoing voice files
/opt/qq-rolebot/data/voice_refs         authorized reference audio and transcripts
/opt/qq-rolebot/stickers                persistent outgoing sticker assets and manifest
/opt/miniconda3/envs/qq-rolebot         Python runtime
/opt/cosyvoice                          optional local CosyVoice runtime
/opt/gptsovits                          optional GPT-SoVITS runtime
/opt/models                             optional local model weights
```

CI/CD preserves `.env`, `.watchdog.env`, `data/`, `voice_refs`, `voice_cache`, `models/`, and
`stickers/` when replacing the app directory.

Store production sticker images and `manifest.yaml` under `/opt/qq-rolebot/stickers`. The deploy
script preserves this directory. Do not commit real sticker packs or generated media to git.
When `MEDIA_REGISTER_CUSTOM_FACES=true`, the bot registers manifest image assets through NapCat
`/add_custom_face` and records file hashes in `/opt/qq-rolebot/data/custom_faces.json`.
NapCat `mface` sending is marketplace-sticker-specific, so locally registered custom faces may still
be sent as `image` segments marked with custom-image `sub_type=1` unless the manifest item includes
complete sendable `mface` metadata.

## 1. Base System Setup

Install OS dependencies and Miniconda:

```bash
sudo apt update
sudo apt install -y curl git openssh-server sqlite3 xvfb
cd /tmp
curl -fsSLo Miniconda3-latest-Linux-x86_64.sh \
  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda3
/opt/miniconda3/bin/conda create -n qq-rolebot python=3.11 -y
```

Do not use the base conda environment for the bot.

If you are doing a first manual copy before CI/CD is ready:

```bash
sudo mkdir -p /opt/qq-rolebot
sudo chown "$USER:$USER" /opt/qq-rolebot
cd /opt/qq-rolebot
/opt/miniconda3/envs/qq-rolebot/bin/python -m pip install -U pip
/opt/miniconda3/envs/qq-rolebot/bin/python -m pip install -e ".[dev]"
cp .env.example .env
```

For an interactive shell:

```bash
source /opt/miniconda3/bin/activate qq-rolebot
```

## 2. Production `.env`

Create `/opt/qq-rolebot/.env` from `.env.example` and fill real values on the server.

Required:

```dotenv
BOT_HOST=127.0.0.1
BOT_PORT=8080
ONEBOT_ACCESS_TOKEN=
BOT_QQ=
ADMIN_USERS=
GROUP_WHITELIST=
DATABASE_PATH=data/rolebot.sqlite3

MODEL_API_BASE=
MODEL_API_KEY=
MODEL_NAME=
MODEL_TIMEOUT_SECONDS=20
MAX_OUTPUT_CHARS=40
```

Persona:

```dotenv
PERSONA_VARIANT=dialect
PERSONA_PATH=personas/default.yaml
```

`dialect` loads `personas/default_dialect.yaml`, the Wuhan dialect persona. `standard` loads `personas/default.yaml`. `custom` loads `PERSONA_PATH`.

Group behavior:

```dotenv
DEFAULT_RANDOM_REPLY_PROBABILITY=3
REPEAT_REPLY_ENABLED=true
REPEAT_REPLY_THRESHOLD=2
CONTEXT_WINDOW_SECONDS=600
KEYWORDS=
FOLLOWUP_WINDOW_SECONDS=90
FOLLOWUP_TRIGGER_KEYWORDS=你,你觉得,你看,怎么看,咋看,怎么样,如何,说话,回话,大哥,重岳,岳饼
```

Existing groups keep their stored probability in SQLite. Use `/bot prob N` in a group to change that group without editing `.env`.
When `REPEAT_REPLY_ENABLED=true`, the bot can join a repeated-message chain after `REPEAT_REPLY_THRESHOLD` consecutive identical unaddressed group messages from at least two users. After it joins, the same text in the same group is cooled down for 10 minutes.
`CONTEXT_WINDOW_SECONDS` controls how far back model context can look. Successful bot replies are stored with user messages, and only records inside this window are included in the next prompt.

Media replies:

```dotenv
MEDIA_REPLY_ENABLED=false
MEDIA_REPLY_PROBABILITY=0
MEDIA_STICKER_ROOT=/opt/qq-rolebot/stickers
MEDIA_STICKER_MANIFEST=/opt/qq-rolebot/stickers/manifest.yaml
MEDIA_REGISTER_CUSTOM_FACES=true
MEDIA_CUSTOM_FACE_CACHE=/opt/qq-rolebot/data/custom_faces.json
```

Active media only appends after a successful model text reply. `MEDIA_REGISTER_CUSTOM_FACES=true`
registers active image assets to the bot QQ account as custom faces. Locally registered custom faces
do not necessarily have the `key` needed for NapCat `mface` sends; the bot sends them as custom
image subtype fallback, or you can provide marketplace `mface` metadata in the manifest for true
`mface` output.

Tools:

```dotenv
TAVILY_API_KEY=
TAVILY_API_BASE=https://api.tavily.com
SEARCH_MAX_RESULTS=5
SEARCH_TIMEOUT_SECONDS=10
SEARCH_COOLDOWN_SECONDS=0
TOOLS_ENABLE_SEARCH=true
TOOLS_ENABLE_PERSONA_SOURCES=true
TOOLS_ENABLE_TIME=true
```

Set `SEARCH_COOLDOWN_SECONDS=0` to remove search cooldown.

Vision:

```dotenv
VISION_MODEL_ENABLED=false
VISION_MODEL_API_BASE=https://your-workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
VISION_MODEL_API_KEY=
VISION_MODEL_NAME=qwen3.7-plus
VISION_MODEL_MODE=hybrid
VISION_MODEL_SEARCH_INPUT=data_url
VISION_MODEL_TIMEOUT_SECONDS=60
VISION_MODEL_SEARCH_TIMEOUT_SECONDS=90
VISION_MODEL_MAX_IMAGES=2
VISION_MODEL_ENABLE_THINKING=true
VISION_MODEL_ENABLE_SEARCH=true
VISION_MODEL_VIDEO_FPS=2

DEBUG_TRACE_DIR=data/debug_traces
DEBUG_TRACE_RETENTION_SECONDS=86400
```

When enabled, visual understanding runs only after the bot has decided to reply. It summarizes current HTTP image, GIF, and video URLs for the main chat model. If a user replies to an image and asks the bot about it, the replied message's media is used before any recent-text fallback. Static images are downloaded once and reused as `data:` inputs for both visual summary and image/web search by default. Optional image/web search can add source or meme context before the pure visual description; if they conflict, the main model is told to prefer the search result. `VISION_MODEL_MODE=search_only` skips the pure visual-description call and uses only image/web search for source, character, and meme-background questions. `VISION_MODEL_SEARCH_INPUT=original_url` sends the original image URL directly to image/web search and avoids local download/encoding, but the URL must be reachable by the model provider. It does not replace the main roleplay model.

Debug traces are always written to `DEBUG_TRACE_DIR` as per-message JSONL files. They include incoming content, media URLs, media source, replied message id, vision/search outputs, final model prompt, model response, and final reply. API keys and Authorization headers are not written. Files older than `DEBUG_TRACE_RETENTION_SECONDS` are pruned when new trace events are written.

Voice:

```dotenv
TTS_ENABLED=false
TTS_BACKEND=aliyun-cosyvoice
TTS_API_URL=https://dashscope.aliyuncs.com
TTS_API_KEY=
TTS_MODEL=cosyvoice-v2
TTS_AUDIO_FORMAT=mp3
TTS_TIMEOUT_SECONDS=30
TTS_TRIGGER_KEYWORDS=语音,说句话,念一下,用你的声音
TTS_MAX_CHARS=80
TTS_COOLDOWN_SECONDS=0
TTS_CACHE_DIR=/opt/qq-rolebot/data/voice_cache
TTS_SPEAKER=
TTS_STYLE=沉稳自然，武汉话日常短句，连贯不逐字
TTS_DIALECT_HINT=武汉话
```

Set `TTS_COOLDOWN_SECONDS=0` to remove voice cooldown.

Never paste real keys into committed files or public logs.

## 3. systemd Service

Create `/etc/systemd/system/qq-rolebot.service`:

```ini
[Unit]
Description=QQ Rolebot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/qq-rolebot
EnvironmentFile=/opt/qq-rolebot/.env
ExecStart=/opt/miniconda3/envs/qq-rolebot/bin/python /opt/qq-rolebot/bot.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable qq-rolebot
sudo systemctl start qq-rolebot
sudo systemctl status qq-rolebot --no-pager
```

View logs:

```bash
journalctl -u qq-rolebot -f
```

Check that the bot is listening for NapCat:

```bash
ss -ltnp | grep ':8080'
```

## 4. NapCatQQ

Install NapCatQQ using its Linux installer or the current project guide:

```bash
curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
bash napcat.sh --tui
```

Use the TUI to log in the QQ alternate account and configure OneBot V11 reverse WebSocket:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

The OneBot access token in NapCatQQ must match `/opt/qq-rolebot/.env`.

On headless Linux, QQ/Electron may need Xvfb and GPU-disabled launch flags. The effective launcher should use the same idea as:

```bash
xvfb-run -a qq --no-sandbox --disable-gpu --disable-dev-shm-usage
```

The exact NapCat service name depends on how it was installed. Discover it with:

```bash
systemctl list-units '*nap*'
systemctl list-units '*qq*'
```

After changing a launcher or unit:

```bash
systemctl daemon-reload
systemctl restart napcat
journalctl -u napcat -n 120 --no-pager
```

Replace `napcat` with the actual unit name if different.

## 5. GitHub Actions CI/CD

Pushes to `master` run `.github/workflows/deploy.yml`.

Required repository secrets:

- `DEPLOY_HOST`: server host.
- `DEPLOY_USER`: usually `root`.
- `DEPLOY_PORT`: usually `22`.
- `DEPLOY_SSH_KEY`: private key whose public key is in the server user's `authorized_keys`.

Workflow behavior:

1. Check out the repository on the GitHub runner.
2. Install Python 3.11 dependencies.
3. Run `ruff`.
4. Run `pytest`.
5. Create `qq-rolebot-source-${{ github.sha }}.tar.gz` with `git archive`.
6. Upload the source archive and `scripts/deploy_server.sh` to `/tmp` on the server.
7. Run the deploy script on the server.

The server no longer needs to fetch from GitHub during deployment. This avoids failures when the server has poor GitHub connectivity.

The deploy script:

- verifies it is operating on `/opt/qq-rolebot`;
- moves the previous app directory to a timestamped backup;
- extracts the uploaded source archive into a fresh app directory;
- restores `.env`, `.watchdog.env`, and runtime directories;
- installs the package in the conda environment;
- runs server-side `ruff` and `pytest`;
- restarts `qq-rolebot.service`;
- waits until `127.0.0.1:8080` accepts TCP connections.

If the final port check fails, the Action should fail and print recent service logs.

## 6. First Group Test

Invite the bot account into a whitelisted group. In that group, an admin runs:

```text
/bot on
```

Then test:

```text
@岳饼 你在吗
/bot status
/bot prob 3
@岳饼 现在几点
```

Expected behavior:

- `/bot status` reports `enabled=True`.
- `@` or reply to the bot should produce a response when the group is enabled.
- Private messages should reply without requiring group enablement.
- Time questions should use current Asia/Shanghai time.

## 7. Admin Operations

Group controls:

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

Useful service commands:

```bash
systemctl restart qq-rolebot
systemctl status qq-rolebot --no-pager
journalctl -u qq-rolebot -n 120 --no-pager
journalctl -u qq-rolebot -f
```

SQLite database backup:

```bash
mkdir -p /opt/qq-rolebot/backups
sqlite3 /opt/qq-rolebot/data/rolebot.sqlite3 ".backup '/opt/qq-rolebot/backups/rolebot-$(date +%Y%m%d%H%M%S).sqlite3'"
```

## 8. Optional Tavily Search

Set:

```dotenv
TAVILY_API_KEY=
TOOLS_ENABLE_SEARCH=true
SEARCH_COOLDOWN_SECONDS=0
```

Restart:

```bash
systemctl restart qq-rolebot
journalctl -u qq-rolebot -n 80 --no-pager
```

Search only runs when the message is private, `@` the bot, or replies to the bot, and contains search/current-information intent.

## 9. Optional Vision Model

Use an OpenAI-compatible vision model when the bot should understand images or meme-style image messages before the main model replies:

```dotenv
VISION_MODEL_ENABLED=true
VISION_MODEL_API_BASE=https://your-workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
VISION_MODEL_API_KEY=
VISION_MODEL_NAME=qwen3.7-plus
VISION_MODEL_MODE=hybrid
VISION_MODEL_SEARCH_INPUT=data_url
VISION_MODEL_TIMEOUT_SECONDS=60
VISION_MODEL_SEARCH_TIMEOUT_SECONDS=90
VISION_MODEL_MAX_IMAGES=2
VISION_MODEL_ENABLE_THINKING=true
VISION_MODEL_ENABLE_SEARCH=true
VISION_MODEL_VIDEO_FPS=2
```

Keep the real API key only in `/opt/qq-rolebot/.env`. The bot sends only current-message or replied-message HTTP media after reply triggering. Messages in the same private chat or same group are handled sequentially, so text follow-ups wait for earlier image recognition in that chat while other chats can continue. Static images are downloaded in memory and reused as `data:` image inputs for visual summary and image/web search by default; the downloaded bytes are not persisted, and trace logs redact the base64 payload. Successful image summaries are saved as short-lived text context keyed by their `[image: ...]` or `[video: ...]` marker, so follow-up questions can reuse the latest summary and replies to a previously summarized image can reuse the matching summary without re-identifying it. OneBot `video` URLs and obvious dynamic media such as `.gif` / `.mp4` use `video_url`. With `VISION_MODEL_ENABLE_SEARCH=true`, image/web search may add a short source or meme-context summary before the pure visual description; if they conflict, the main model is told to prefer the search result. Set `VISION_MODEL_MODE=search_only` to skip pure visual description and use only image/web search. Set `VISION_MODEL_SEARCH_INPUT=original_url` to pass the original image URL directly to image/web search, avoiding local download and base64 encoding when the media URL is externally reachable. The final reply still comes from the main chat model.

## 10. Optional TTS Backends

### Generic HTTP TTS

Run a local TTS service bound to `127.0.0.1`, then set:

```dotenv
TTS_ENABLED=true
TTS_BACKEND=generic
TTS_API_URL=http://127.0.0.1:5005
TTS_CACHE_DIR=/opt/qq-rolebot/data/voice_cache
```

The bot expects `POST /synthesize` to return either raw audio bytes or JSON containing base64 audio.

### GPT-SoVITS CPU Trial

Run GPT-SoVITS as a separate local service, then set:

```dotenv
TTS_ENABLED=true
TTS_BACKEND=gptsovits
TTS_API_URL=http://127.0.0.1:9880
TTS_CACHE_DIR=/opt/qq-rolebot/data/voice_cache
TTS_REF_AUDIO_PATH=/opt/qq-rolebot/data/voice_refs/chongyue/topolect/cn_001.wav
TTS_PROMPT_TEXT=
TTS_PROMPT_LANG=zh
TTS_TEXT_LANG=zh
TTS_TIMEOUT_SECONDS=120
```

`TTS_PROMPT_TEXT` must match the selected authorized reference audio. Keep GPT-SoVITS source, model weights, converted datasets, and generated files under `/opt/gptsovits`, `/opt/models/gptsovits`, and `/opt/qq-rolebot/data`.

### Alibaba Cloud Model Studio CosyVoice

Create or select a CosyVoice voice in Alibaba Cloud Model Studio. Store only the API key and voice id in `/opt/qq-rolebot/.env`:

```dotenv
TTS_ENABLED=true
TTS_BACKEND=aliyun-cosyvoice
TTS_API_URL=https://dashscope.aliyuncs.com
TTS_API_KEY=
TTS_MODEL=cosyvoice-v2
TTS_AUDIO_FORMAT=mp3
TTS_TEXT_LANG=zh
TTS_SPEAKER=
TTS_STYLE=沉稳自然，武汉话日常短句，连贯不逐字
TTS_DIALECT_HINT=武汉话
TTS_TIMEOUT_SECONDS=30
TTS_CACHE_DIR=/opt/qq-rolebot/data/voice_cache
```

`TTS_SPEAKER` is the Alibaba voice id, not a local path. The client downloads generated audio from the temporary URL returned by DashScope and caches it under `TTS_CACHE_DIR`.

## 11. NapCat Account Watchdog

The watchdog is a separate one-shot script run by systemd timer. It checks the bot service, NapCat
service, bot TCP port, OneBot reverse WebSocket connection, optional OneBot HTTP API account status,
and recent NapCat logs. When the account appears offline, it sends a QQ Mail alert and attaches the
newest fresh QR image when available. If the administrator replies to the alert later, the watchdog
can refresh NapCat and send a new QR email.

For stronger account-state detection, enable a NapCat OneBot HTTP API listener bound only to
`127.0.0.1`, then set `WATCHDOG_REQUIRE_ONEBOT_HTTP_API=true`. The watchdog calls
`get_login_info` and `get_status`; failed API calls, nonzero `retcode`, or `online=false` make the
account unhealthy. Do not expose this HTTP API to the public internet.

HTML-capable mail clients also show a `获取新二维码` button. When
`WATCHDOG_CLICK_PUBLIC_BASE_URL` is configured, the button opens a server endpoint that refreshes
NapCat and sends a fresh QR email to the administrator mailbox. The web page does not display the
QR image. If no public click URL is configured, the button falls back to the older `mailto:` reply
draft flow.

Create `/opt/qq-rolebot/.watchdog.env` on the server. This file is server-only and must be mode
`600`.

```dotenv
WATCHDOG_BOT_SERVICE=qq-rolebot.service
WATCHDOG_NAPCAT_SERVICE=napcat.service
WATCHDOG_HOST=127.0.0.1
WATCHDOG_PORT=8080
WATCHDOG_REQUIRE_ONEBOT_CONNECTION=true
WATCHDOG_REQUIRE_ONEBOT_HTTP_API=false
WATCHDOG_ONEBOT_HTTP_API_BASE=http://127.0.0.1:3001
WATCHDOG_ONEBOT_HTTP_API_TOKEN=
WATCHDOG_ONEBOT_HTTP_API_TIMEOUT_SECONDS=5
WATCHDOG_LOG_WINDOW_MINUTES=10
WATCHDOG_STATE_PATH=/opt/qq-rolebot/data/account_watchdog_state.json
WATCHDOG_SEND_RECOVERY=true
WATCHDOG_QR_PATH=
WATCHDOG_QR_GLOB=/root/Napcat/**/cache/qrcode.png
WATCHDOG_QR_MAX_AGE_SECONDS=120
WATCHDOG_QR_REFRESH_COMMAND="systemctl restart napcat.service"
WATCHDOG_QR_REFRESH_WAIT_SECONDS=15
WATCHDOG_REPLY_ENABLED=true
WATCHDOG_REPLY_ALLOWED_SENDERS=admin@example.com
WATCHDOG_REPLY_KEYWORDS=qr,qrcode,二维码,扫码,登录
WATCHDOG_QR_REPLY_COOLDOWN_SECONDS=60
WATCHDOG_CLICK_PUBLIC_BASE_URL=
WATCHDOG_CLICK_HOST=127.0.0.1
WATCHDOG_CLICK_PORT=18081
WATCHDOG_CLICK_PATH_PREFIX=/watchdog/qr
WATCHDOG_CLICK_TOKEN_TTL_SECONDS=86400

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=sender@qq.com
SMTP_PASSWORD=qq-mail-authorization-code
ALERT_EMAIL_FROM=sender@qq.com
ALERT_EMAIL_TO=admin@example.com

IMAP_HOST=imap.qq.com
IMAP_PORT=993
IMAP_USER=sender@qq.com
IMAP_PASSWORD=qq-mail-authorization-code
```

`SMTP_PASSWORD` and `IMAP_PASSWORD` are QQ Mail authorization codes, not the QQ account password.
Enable SMTP and IMAP in QQ Mail settings before using this file.

Install `/etc/systemd/system/napcat-account-watchdog.service`:

```ini
[Unit]
Description=NapCat Account Watchdog
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/qq-rolebot
EnvironmentFile=/opt/qq-rolebot/.watchdog.env
ExecStart=/opt/miniconda3/envs/qq-rolebot/bin/python /opt/qq-rolebot/scripts/napcat_account_watchdog.py
User=root
```

Install `/etc/systemd/system/napcat-account-watchdog.timer`:

```ini
[Unit]
Description=Run NapCat account watchdog every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
```

Enable the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl disable --now napcat-watchdog.timer 2>/dev/null || true
sudo systemctl enable --now napcat-account-watchdog.timer
sudo systemctl start napcat-account-watchdog.service
sudo journalctl -u napcat-account-watchdog -n 80 --no-pager -l
```

Optional one-click QR button service:

```ini
[Unit]
Description=NapCat QR Click Webhook
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/qq-rolebot
EnvironmentFile=/opt/qq-rolebot/.watchdog.env
ExecStart=/opt/miniconda3/envs/qq-rolebot/bin/python /opt/qq-rolebot/scripts/napcat_account_watchdog.py --serve-click-webhook
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

For a quick HTTP trial without a reverse proxy, set:

```dotenv
WATCHDOG_CLICK_PUBLIC_BASE_URL=http://SERVER_PUBLIC_IP:18081
WATCHDOG_CLICK_HOST=0.0.0.0
WATCHDOG_CLICK_PORT=18081
WATCHDOG_CLICK_PATH_PREFIX=/watchdog/qr
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now napcat-qr-click.service
sudo systemctl status napcat-qr-click --no-pager -l
```

For long-term use, put the click service behind HTTPS and set
`WATCHDOG_CLICK_PUBLIC_BASE_URL` to that HTTPS origin. Keep the rolebot OneBot endpoint on
`127.0.0.1:8080`; do not expose it for this button.

Manual verification:

```bash
sudo systemctl status napcat-account-watchdog.timer --no-pager -l
sudo systemctl status napcat-qr-click --no-pager -l
sudo bash -lc 'set -a; . /opt/qq-rolebot/.watchdog.env; set +a; WATCHDOG_PORT=18080 /opt/miniconda3/envs/qq-rolebot/bin/python /opt/qq-rolebot/scripts/napcat_account_watchdog.py'
sudo journalctl -u napcat-account-watchdog -n 80 --no-pager -l
sudo journalctl -u napcat-qr-click -n 80 --no-pager -l
```

The QR attachment is sensitive login material. Do not copy it into git, paste it into public logs,
or forward it outside the administrator mailbox.

## 12. Troubleshooting

### NapCat reverse WebSocket gets ECONNREFUSED

This means NapCat reached `127.0.0.1`, but nothing was accepting connections on port `8080`.

Check:

```bash
systemctl status qq-rolebot --no-pager
journalctl -u qq-rolebot -n 120 --no-pager
ss -ltnp | grep ':8080'
grep -E '^(BOT_HOST|BOT_PORT)=' /opt/qq-rolebot/.env
```

`BOT_PORT` must match the port in NapCat's reverse WebSocket URL. CI/CD now waits for `127.0.0.1:8080`, so persistent refused connections should fail deployment.

### Private chat replies but group chat does not

Check:

```text
/bot status
/bot on
```

Also confirm:

- the group ID is in `GROUP_WHITELIST`;
- the message actually `@` the bot or replies to one of its messages;
- the group is not muted;
- the model API is healthy.

### The bot is too noisy

Use group controls:

```text
/bot prob 0
/bot mute 10m
/bot off
```

### QQ login expires or the account is kicked offline

NapCat may log a `bot_offline` notice when QQ decides the login is invalid. In practice, QR re-login is the safest recovery path. Password-based unattended login is risky and may still be rejected by QQ risk control.

Recommended operational posture:

- keep NapCat on the Linux server rather than a Windows desktop that may sleep;
- keep the NapCat service supervised by systemd;
- monitor logs for `bot_offline`;
- be ready to rescan the login QR code when QQ invalidates the session.

### Linux QQ or NapCat crashes with GPU process errors

If logs contain `GPU process launch failed` and `GPU process isn't usable. Goodbye.`, the QQ/Electron process crashed before NapCat could keep the gateway alive.

Use Xvfb and GPU-disabled flags:

```bash
xvfb-run -a qq --no-sandbox --disable-gpu --disable-dev-shm-usage
```

Then restart the actual NapCat/QQ unit and inspect logs:

```bash
systemctl daemon-reload
systemctl restart napcat
journalctl -u napcat -n 120 --no-pager
```

### CI/CD fails

Open the GitHub Actions run. If server-side deploy fails, reproduce on the server with the uploaded script if available:

```bash
bash /tmp/qq-rolebot-deploy.sh '/tmp/qq-rolebot-source-<sha>.tar.gz' master '<sha>'
```

Common causes:

- missing or invalid GitHub Actions secrets;
- SSH public key not installed in `authorized_keys`;
- `/opt/miniconda3/envs/qq-rolebot` missing;
- `.env` missing required variables;
- tests failing on the server;
- service starts but does not listen on `127.0.0.1:8080`.
