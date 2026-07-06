# QQ Rolebot

NapCatQQ + NoneBot2 roleplay bot for QQ group chat.

## Development

```bash
conda create -n qq-rolebot python=3.11 -y
conda activate qq-rolebot
python -m pip install -e ".[dev]"
copy .env.example .env
pytest
```

## Runtime

Run the bot:

```bash
python bot.py
```

Configure NapCatQQ OneBot V11 reverse WebSocket to:

```text
ws://127.0.0.1:8080/onebot/v11/ws
```

Set the same access token in NapCatQQ and `ONEBOT_ACCESS_TOKEN`.

## Tools

The bot can answer current-time questions directly and can use Tavily search when a private
message or explicitly addressed group message asks for current external information.

Set `TAVILY_API_KEY` in `.env` to enable web search. Do not commit real API keys.
Persona source lookup reads the `Sources` list from `personas/default.yaml`.

## Voice Replies

Voice replies are optional and disabled by default. Set `TTS_ENABLED=true` and point
`TTS_API_URL` at a local TTS HTTP service to allow explicit voice requests. The default
`TTS_BACKEND=generic` calls `POST /synthesize`; `TTS_BACKEND=gptsovits` calls GPT-SoVITS
`POST /tts` and uses `TTS_REF_AUDIO_PATH`, `TTS_PROMPT_TEXT`, `TTS_PROMPT_LANG`, and
`TTS_TEXT_LANG`.
Large runtime artifacts such as model weights, reference audio, generated voice cache files, and
container images should live only on the server, not in this repository.

## Group Follow-Ups

After someone mentions or replies to the bot in a group, `FOLLOWUP_WINDOW_SECONDS` opens a short
same-user follow-up window. Messages in that window still need to look addressed to the bot, based
on `FOLLOWUP_TRIGGER_KEYWORDS` or question marks, before the bot replies.

## Deployment

Pushes to `master` run GitHub Actions CI and deploy to `/opt/qq-rolebot` on the server.
The deployment preserves server-only runtime files such as `.env`, `data/`, model weights,
reference audio, and generated voice cache files.

Required GitHub repository secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_PORT`
- `DEPLOY_SSH_KEY`
