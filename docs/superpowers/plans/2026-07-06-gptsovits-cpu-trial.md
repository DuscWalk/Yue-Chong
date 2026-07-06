# GPT-SoVITS CPU Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a CPU-only GPT-SoVITS trial for explicit QQ voice replies without storing model assets in git or the local workspace.

**Architecture:** Keep the bot text-first and reuse the existing `VoiceService`. Add a GPT-SoVITS backend to `TTSClient` so the bot can call GPT-SoVITS `POST /tts` directly, while model weights, reference audio, and generated cache stay on the server.

**Tech Stack:** Python 3.11, httpx, pytest, NoneBot OneBot V11, GPT-SoVITS CPU inference, systemd.

---

### Task 1: Bot-Side GPT-SoVITS Client Adapter

**Files:**
- Modify: `qq_rolebot/config.py`
- Modify: `qq_rolebot/tts_client.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_config.py`
- Test: `tests/test_tts_client.py`

- [ ] Add settings for `TTS_BACKEND`, `TTS_REF_AUDIO_PATH`, `TTS_PROMPT_TEXT`, `TTS_PROMPT_LANG`, and `TTS_TEXT_LANG`.
- [ ] Add a failing test that `TTSClient(backend="gptsovits")` posts to `/tts` with GPT-SoVITS-compatible fields and accepts raw `audio/wav`.
- [ ] Implement the smallest backend switch needed to pass the test.
- [ ] Wire settings into the plugin-created `TTSClient`.
- [ ] Run `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_config.py tests/test_tts_client.py -q`.

### Task 2: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] Document the GPT-SoVITS CPU backend variables.
- [ ] State that model weights and reference audio stay under server-only paths.

### Task 3: Server Deployment Trial

**Files:**
- Server-only: `/opt/gptsovits`
- Server-only: `/opt/models/gptsovits`
- Server-only: `/etc/systemd/system/gptsovits.service`
- Server-only: `/opt/qq-rolebot/.env`

- [ ] Clone GPT-SoVITS on the server only.
- [ ] Create a separate conda environment for GPT-SoVITS CPU inference.
- [ ] Start its API service bound to `127.0.0.1`.
- [ ] Set bot `.env` to `TTS_ENABLED=true`, `TTS_BACKEND=gptsovits`, and point `TTS_API_URL` at the local service.
- [ ] Use one existing authorized dialect reference audio and transcript from `/opt/qq-rolebot/data/voice_refs/chongyue/topolect`.
- [ ] Restart `qq-rolebot.service`.

### Task 4: Verification

- [ ] Run local ruff and pytest.
- [ ] Push the bot-side adapter to GitHub so CI/CD can deploy it.
- [ ] On the server, call the GPT-SoVITS API with a short Chinese text and verify a wav file is produced.
- [ ] Confirm `gptsovits.service` and `qq-rolebot.service` are active.
- [ ] If CPU inference is too slow or memory-heavy, turn `TTS_ENABLED=false` and keep the code adapter disabled.

