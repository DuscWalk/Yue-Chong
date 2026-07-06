# Rolebot TTS Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional voice replies that call a local TTS service and send OneBot `record` segments.

**Architecture:** Keep `ChatService` text-first. Add TTS settings, a voice policy, a TTS HTTP client, a voice rendering service, and plugin sending logic that falls back to text when voice cannot be generated.

**Tech Stack:** Python 3.11, httpx, NoneBot2 OneBot V11, pytest, ruff.

**Artifact Policy:** Do not store model weights, container images, reference audio, converted datasets, or generated voice cache files in the local workspace or git repository. Put large/runtime artifacts only on the server, under paths documented in the deployment guide.

---

### Task 1: TTS Settings

**Files:**
- Modify: `qq_rolebot/config.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Add tests asserting TTS defaults are disabled and overrides are parsed from a mapping.

- [ ] **Step 2: Run settings tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_config.py -q`

Expected: fail because `Settings` has no TTS fields.

- [ ] **Step 3: Implement settings**

Add TTS fields to `Settings`, parse positive integer values, parse trigger keywords with
`parse_str_list`, and default `TTS_ENABLED=false`.

- [ ] **Step 4: Update docs and env example**

Add empty/default TTS variables and a short deployment note for a local CosyVoice-compatible
HTTP service. Document server-only paths for model weights, reference audio, and voice cache.

- [ ] **Step 5: Verify**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_config.py -q`

Expected: pass.

### Task 2: Voice Policy

**Files:**
- Create: `qq_rolebot/voice_policy.py`
- Test: `tests/test_voice_policy.py`

- [ ] **Step 1: Write failing policy tests**

Cover private voice keyword, addressed group voice keyword, ignored unaddressed group request,
and cooldown after a successful voice send.

- [ ] **Step 2: Run policy tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_voice_policy.py -q`

Expected: fail because `qq_rolebot.voice_policy` does not exist.

- [ ] **Step 3: Implement policy**

Create `VoicePolicy` with `should_attempt(message, now)` and `record(message, now)`.

- [ ] **Step 4: Verify**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_voice_policy.py -q`

Expected: pass.

### Task 3: TTS Client

**Files:**
- Create: `qq_rolebot/tts_client.py`
- Test: `tests/test_tts_client.py`

- [ ] **Step 1: Write failing client tests**

Use `httpx.MockTransport` to verify raw audio bytes, JSON base64 audio, and HTTP failure handling.

- [ ] **Step 2: Run client tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tts_client.py -q`

Expected: fail because `qq_rolebot.tts_client` does not exist.

- [ ] **Step 3: Implement client**

Create `TTSClient.synthesize(...)` returning `TTSResult(ok, audio, extension, error)`.

- [ ] **Step 4: Verify**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tts_client.py -q`

Expected: pass.

### Task 4: Voice Service

**Files:**
- Create: `qq_rolebot/voice_service.py`
- Test: `tests/test_voice_service.py`

- [ ] **Step 1: Write failing service tests**

Verify disabled/no-trigger returns no voice, success writes a file and records cooldown, and
client failure returns no voice.

- [ ] **Step 2: Run service tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_voice_service.py -q`

Expected: fail because `qq_rolebot.voice_service` does not exist.

- [ ] **Step 3: Implement service**

Create `VoiceService.maybe_render(message, reply)` returning `VoiceRenderResult`.

- [ ] **Step 4: Verify**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_voice_service.py -q`

Expected: pass.

### Task 5: Plugin Integration

**Files:**
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing plugin tests**

Verify the plugin sends `record` when voice rendering returns a file and sends text when voice
rendering returns no file.

- [ ] **Step 2: Run plugin tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_plugin_smoke.py -q`

Expected: fail because the plugin always sends text.

- [ ] **Step 3: Wire voice service**

Build `VoiceService` only when TTS is enabled and an API URL is configured. In `handle_message`,
ask it to render voice after receiving the text reply.

- [ ] **Step 4: Verify**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_plugin_smoke.py -q`

Expected: pass.

### Task 6: Final Verification and Commit

**Files:**
- All changed files

- [ ] **Step 1: Run full tests**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q`

Expected: pass.

- [ ] **Step 2: Run lint**

Run: `D:\Anaconda\envs\qq-rolebot\python.exe -m ruff check .`

Expected: pass.

- [ ] **Step 3: Commit**

Run:

```bash
git add .
git commit -m "feat: add optional tts voice replies"
```
