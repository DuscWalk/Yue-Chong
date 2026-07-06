# Deployment

Target server: Ubuntu.

## 1. Install project

```bash
sudo apt update
sudo apt install -y curl git
cd /tmp
curl -fsSLo Miniconda3-latest-Linux-x86_64.sh \
  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda3
/opt/miniconda3/bin/conda create -n qq-rolebot python=3.11 -y
cd /opt
sudo mkdir -p qq-rolebot
sudo chown "$USER:$USER" qq-rolebot
cd /opt/qq-rolebot
/opt/miniconda3/bin/conda run -n qq-rolebot python -m pip install -U pip
/opt/miniconda3/bin/conda run -n qq-rolebot python -m pip install -e ".[dev]"
cp .env.example .env
```

For an interactive shell:

```bash
source /opt/miniconda3/bin/activate qq-rolebot
```

Edit `.env` and set:

- `ONEBOT_ACCESS_TOKEN`
- `BOT_QQ`
- `ADMIN_USERS`
- `GROUP_WHITELIST`
- `MODEL_API_BASE`
- `MODEL_API_KEY`
- `MODEL_NAME`

Optional tool settings:

- `TAVILY_API_KEY` enables Tavily web search.
- `TOOLS_ENABLE_TIME`, `TOOLS_ENABLE_SEARCH`, and `TOOLS_ENABLE_PERSONA_SOURCES` control tool
  availability.
- `TTS_ENABLED` and `TTS_API_URL` enable optional voice replies through a local TTS HTTP service.
- `FOLLOWUP_WINDOW_SECONDS` and `FOLLOWUP_TRIGGER_KEYWORDS` control short same-user group
  follow-up windows after an `@` or reply.

Server-only TTS artifact paths:

- `/opt/cosyvoice` for the CosyVoice runtime service.
- `/opt/models/cosyvoice` for model weights.
- `/opt/qq-rolebot/data/voice_refs/chongyue` for authorized reference audio.
- `/opt/qq-rolebot/data/voice_cache` for generated outgoing voice files.

Do not copy model weights, container images, reference audio, converted datasets, or generated
voice cache files into the local workspace or git repository.

## 2. Run tests on the server

```bash
cd /opt/qq-rolebot
/opt/miniconda3/bin/conda run -n qq-rolebot pytest
```

## 3. Install NapCatQQ

Follow the current NapCatQQ Linux guide:

```bash
curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
bash napcat.sh --tui
```

Use the TUI to log in the QQ alternate account and configure OneBot V11 reverse WebSocket.

Reverse WebSocket URL:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

Set the same access token in NapCatQQ and `.env`.

## 4. Create systemd service

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
sudo systemctl status qq-rolebot
```

View logs:

```bash
journalctl -u qq-rolebot -f
```

### Tavily Search

On the server, edit `/opt/qq-rolebot/.env` and set:

```dotenv
TAVILY_API_KEY=
```

Restart:

```bash
systemctl restart qq-rolebot
journalctl -u qq-rolebot -n 80 --no-pager
```

Never paste the real key into committed files or public logs.

### Optional CosyVoice TTS

Run CosyVoice as a separate service bound to `127.0.0.1`, then set:

```dotenv
TTS_ENABLED=true
TTS_API_URL=http://127.0.0.1:5005
TTS_CACHE_DIR=/opt/qq-rolebot/data/voice_cache
```

The bot expects `POST /synthesize` to return either raw audio bytes or JSON containing base64
audio. If TTS fails or times out, the bot falls back to the original text reply.

## 5. First group test

In the whitelisted QQ group:

```text
/bot on
```

Then mention the QQ alternate account. The bot should reply once, stay within rate limits, and ignore non-whitelisted groups.
