# Deployment

This document is the production runbook for the QQ rolebot. The current production target is a Linux server, with Python running from a dedicated conda environment and NapCatQQ running as the QQ gateway.

Do not put secrets in this repository. Keep API keys, QQ login data, voice references, generated audio, model weights, and container images on the server only.

## Server Layout

Expected paths:

```text
/opt/qq-rolebot                         app code deployed by CI/CD
/opt/qq-rolebot/.env                    production secrets and runtime config
/opt/qq-rolebot/data/rolebot.sqlite3    group settings and recent context
/opt/qq-rolebot/data/voice_cache        generated outgoing voice files
/opt/qq-rolebot/data/voice_refs         authorized reference audio and transcripts
/opt/miniconda3/envs/qq-rolebot         Python runtime
/opt/cosyvoice                          optional local CosyVoice runtime
/opt/gptsovits                          optional GPT-SoVITS runtime
/opt/models                             optional local model weights
```

CI/CD preserves `.env`, `data/`, `voice_refs/`, `voice_cache/`, and `models/` when replacing the app directory.

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
KEYWORDS=
FOLLOWUP_WINDOW_SECONDS=90
FOLLOWUP_TRIGGER_KEYWORDS=你,你觉得,你看,怎么看,咋看,怎么样,如何,说话,回话,大哥,重岳,岳饼
```

Existing groups keep their stored probability in SQLite. Use `/bot prob N` in a group to change that group without editing `.env`.

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
- restores `.env` and runtime directories;
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

## 9. Optional TTS Backends

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

## 10. Troubleshooting

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
