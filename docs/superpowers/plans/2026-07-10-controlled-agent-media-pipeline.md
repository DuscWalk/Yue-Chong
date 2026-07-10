# Controlled Agent Media Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled agent pipeline with ordered multi-message replies, temporary media repeat, and persistent server sticker append support.

**Architecture:** Keep deterministic trigger and repeat decisions outside the model. Introduce transport-neutral `OutgoingReply` messages, render them at the NoneBot boundary, move model prompting into a controlled `AgentRunner`, and append active stickers only after model text passes guardrails. Temporary repeat media stays in process memory; active sticker assets live in a server-persistent directory.

**Tech Stack:** Python 3.11, NoneBot2 OneBot V11, PyYAML, pytest, ruff, SQLite storage for text context only.

---

## File Structure

- Create `qq_rolebot/outgoing.py`
  - Defines `OutgoingMessage` and `OutgoingReply`.
  - Keeps transport-neutral constructors for text, image, face, and record messages.

- Create `qq_rolebot/repeat_policy.py`
  - Owns in-process repeat tracking.
  - Produces `OutgoingReply` for text, image, or QQ face repeat chains.
  - Does not write temporary media into SQLite.

- Create `qq_rolebot/stickers.py`
  - Loads a YAML manifest from a server-persistent asset root.
  - Selects known local sticker files by tag and weight.

- Create `qq_rolebot/reply_enhancer.py`
  - Appends an active sticker image after a successful model text reply.
  - Never creates a standalone reply.

- Create `qq_rolebot/agent_runner.py`
  - Encapsulates prompt construction, model invocation, and guardrail cleanup for model text.
  - Receives controlled tool/vision context from `ChatService`.

- Modify `qq_rolebot/message_segments.py`
  - Extract repeat-capable image and face references separately from text summaries.

- Modify `qq_rolebot/policy.py`
  - Extend `IncomingMessage` with repeat media fields.

- Modify `qq_rolebot/service.py`
  - Return `OutgoingReply` internally through a new `handle_reply`.
  - Keep `handle` as a text compatibility wrapper during migration.
  - Use `RepeatTracker`, `AgentRunner`, and `ReplyEnhancer`.

- Modify `qq_rolebot/plugins/roleplay_chat.py`
  - Render ordered `OutgoingReply` messages as separate OneBot sends.
  - Keep existing TTS behavior conservative: when voice is sent, skip active sticker image.

- Modify `qq_rolebot/config.py`, `.env.example`, `README.md`, `docs/deployment.md`, and `scripts/deploy_server.sh`
  - Add media settings and preserve the server sticker directory.

- Tests:
  - Create `tests/test_outgoing.py`
  - Create `tests/test_repeat_policy.py`
  - Create `tests/test_stickers.py`
  - Create `tests/test_reply_enhancer.py`
  - Create `tests/test_agent_runner.py`
  - Modify `tests/test_message_segments.py`
  - Modify `tests/test_plugin_smoke.py`
  - Modify `tests/test_service.py`
  - Modify `tests/test_config.py`
  - Modify `tests/test_deploy_script.py`

---

### Task 1: Add Outgoing Reply Types And Renderer

**Files:**
- Create: `qq_rolebot/outgoing.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_outgoing.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write outgoing type tests**

Add `tests/test_outgoing.py`:

```python
from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply


def test_outgoing_reply_text_constructor() -> None:
    reply = OutgoingReply.text("你好", source="model")

    assert reply.source == "model"
    assert reply.text == "你好"
    assert reply.messages == [OutgoingMessage(kind="text", text="你好", source="model")]


def test_outgoing_reply_filters_empty_messages() -> None:
    reply = OutgoingReply(source="model", messages=[OutgoingMessage(kind="text", text="")])

    assert reply.is_empty is True
    assert reply.text == ""
```

- [ ] **Step 2: Run outgoing type tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_outgoing.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'qq_rolebot.outgoing'`.

- [ ] **Step 3: Implement outgoing types**

Create `qq_rolebot/outgoing.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


OutgoingKind = Literal["text", "image", "face", "record"]


@dataclass(frozen=True)
class OutgoingMessage:
    kind: OutgoingKind
    text: str = ""
    file: str = ""
    url: str = ""
    face_id: str = ""
    source: str = ""

    @property
    def is_empty(self) -> bool:
        if self.kind == "text":
            return not self.text.strip()
        if self.kind in {"image", "record"}:
            return not (self.file.strip() or self.url.strip())
        if self.kind == "face":
            return not self.face_id.strip()
        return True


@dataclass(frozen=True)
class OutgoingReply:
    source: str
    messages: list[OutgoingMessage] = field(default_factory=list)

    @classmethod
    def text(cls, text: str, *, source: str) -> "OutgoingReply":
        return cls(source=source, messages=[OutgoingMessage(kind="text", text=text, source=source)])

    @property
    def is_empty(self) -> bool:
        return not [message for message in self.messages if not message.is_empty]

    @property
    def text(self) -> str:
        return "\n".join(
            message.text.strip()
            for message in self.messages
            if message.kind == "text" and message.text.strip()
        )

    def with_message(self, message: OutgoingMessage) -> "OutgoingReply":
        return OutgoingReply(source=self.source, messages=[*self.messages, message])
```

- [ ] **Step 4: Run outgoing type tests and verify they pass**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_outgoing.py -q
```

Expected: PASS.

- [ ] **Step 5: Write plugin renderer test**

Append to `tests/test_plugin_smoke.py`:

```python
async def test_render_outgoing_reply_sends_text_and_image_separately(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply

    class FakeBot:
        def __init__(self):
            self.sent = []

        async def send(self, event, message):
            self.sent.append(str(message))

    bot = FakeBot()
    reply = OutgoingReply(
        source="model",
        messages=[
            OutgoingMessage(kind="text", text="一切安好。"),
            OutgoingMessage(kind="image", file="/opt/qq-rolebot/stickers/calm.webp"),
        ],
    )

    await module.send_outgoing_reply(bot, object(), reply)

    assert len(bot.sent) == 2
    assert "一切安好" in bot.sent[0]
    assert "image" in bot.sent[1]
```

- [ ] **Step 6: Run plugin renderer test and verify it fails**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_plugin_smoke.py::test_render_outgoing_reply_sends_text_and_image_separately -q
```

Expected: FAIL with `AttributeError` for missing `send_outgoing_reply`.

- [ ] **Step 7: Implement plugin renderer helper**

In `qq_rolebot/plugins/roleplay_chat.py`, import outgoing types:

```python
from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
```

Add before `handle_message`:

```python
def render_outgoing_message(message: OutgoingMessage) -> MessageSegment | None:
    if message.kind == "text" and message.text.strip():
        return MessageSegment.text(message.text.strip())
    if message.kind == "image":
        value = message.file.strip() or message.url.strip()
        return MessageSegment.image(value) if value else None
    if message.kind == "face" and message.face_id.strip():
        return MessageSegment.face(int(message.face_id))
    if message.kind == "record":
        value = message.file.strip() or message.url.strip()
        return MessageSegment.record(value) if value else None
    return None


async def send_outgoing_reply(bot: Bot, event: MessageEvent, reply: OutgoingReply) -> None:
    for outgoing_message in reply.messages:
        segment = render_outgoing_message(outgoing_message)
        if segment is not None:
            await bot.send(event, segment)
```

- [ ] **Step 8: Run renderer tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_outgoing.py tests/test_plugin_smoke.py::test_render_outgoing_reply_sends_text_and_image_separately -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add qq_rolebot/outgoing.py qq_rolebot/plugins/roleplay_chat.py tests/test_outgoing.py tests/test_plugin_smoke.py
git commit -m "feat: add outgoing reply renderer"
```

---

### Task 2: Add Media Configuration

**Files:**
- Modify: `qq_rolebot/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write config tests**

Append to `tests/test_config.py`:

```python
def test_load_settings_reads_media_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.media_reply_enabled is False
    assert settings.media_reply_probability == 0
    assert settings.media_sticker_root.as_posix() == "stickers"
    assert settings.media_sticker_manifest.as_posix() == "stickers/manifest.yaml"


def test_load_settings_reads_media_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "MEDIA_REPLY_ENABLED": "true",
            "MEDIA_REPLY_PROBABILITY": "35",
            "MEDIA_STICKER_ROOT": "/opt/qq-rolebot/stickers",
            "MEDIA_STICKER_MANIFEST": "/opt/qq-rolebot/stickers/custom.yaml",
        }
    )

    settings = load_settings(env)

    assert settings.media_reply_enabled is True
    assert settings.media_reply_probability == 35
    assert settings.media_sticker_root.as_posix() == "/opt/qq-rolebot/stickers"
    assert settings.media_sticker_manifest.as_posix() == "/opt/qq-rolebot/stickers/custom.yaml"


def test_load_settings_rejects_invalid_media_probability() -> None:
    env = complete_env()
    env["MEDIA_REPLY_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="MEDIA_REPLY_PROBABILITY"):
        load_settings(env)
```

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_config.py::test_load_settings_reads_media_defaults tests/test_config.py::test_load_settings_reads_media_overrides tests/test_config.py::test_load_settings_rejects_invalid_media_probability -q
```

Expected: FAIL with missing `Settings.media_reply_enabled`.

- [ ] **Step 3: Implement settings fields**

In `qq_rolebot/config.py`, add to `Settings`:

```python
    media_reply_enabled: bool
    media_reply_probability: int
    media_sticker_root: Path
    media_sticker_manifest: Path
```

In `load_settings`, after random reply probability validation:

```python
    media_reply_probability = _int(env, "MEDIA_REPLY_PROBABILITY", 0)
    if media_reply_probability < 0 or media_reply_probability > 100:
        raise ConfigError("MEDIA_REPLY_PROBABILITY must be between 0 and 100")
```

Before `return Settings(...)`:

```python
    media_sticker_root = Path(env.get("MEDIA_STICKER_ROOT", "stickers").strip() or "stickers")
    raw_media_manifest = env.get("MEDIA_STICKER_MANIFEST", "").strip()
    media_sticker_manifest = (
        Path(raw_media_manifest) if raw_media_manifest else media_sticker_root / "manifest.yaml"
    )
```

Add to the `Settings(...)` constructor:

```python
        media_reply_enabled=_bool(env, "MEDIA_REPLY_ENABLED", False),
        media_reply_probability=media_reply_probability,
        media_sticker_root=media_sticker_root,
        media_sticker_manifest=media_sticker_manifest,
```

- [ ] **Step 4: Update `.env.example`**

Add after `SENSITIVE_WORDS=`:

```text
MEDIA_REPLY_ENABLED=false
MEDIA_REPLY_PROBABILITY=0
MEDIA_STICKER_ROOT=stickers
MEDIA_STICKER_MANIFEST=
```

- [ ] **Step 5: Run config tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add qq_rolebot/config.py .env.example tests/test_config.py
git commit -m "feat: add media reply settings"
```

---

### Task 3: Add Sticker Manifest Loader

**Files:**
- Create: `qq_rolebot/stickers.py`
- Test: `tests/test_stickers.py`

- [ ] **Step 1: Write sticker loader tests**

Create `tests/test_stickers.py`:

```python
from pathlib import Path

from qq_rolebot.stickers import StickerLibrary


def test_sticker_library_loads_existing_manifest_item(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    (root / "chongyue").mkdir(parents=True)
    image = root / "chongyue" / "calm.webp"
    image.write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: calm
    file: chongyue/calm.webp
    tags: [calm, reply]
    weight: 2
""".strip(),
        encoding="utf-8",
    )

    library = StickerLibrary(root=root, manifest_path=manifest)

    item = library.select(tags=["reply"], random_value=0)

    assert item is not None
    assert item.id == "calm"
    assert item.path == image


def test_sticker_library_skips_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: missing
    file: missing.webp
    tags: [reply]
    weight: 1
""".strip(),
        encoding="utf-8",
    )

    library = StickerLibrary(root=root, manifest_path=manifest)

    assert library.select(tags=["reply"], random_value=0) is None


def test_sticker_library_missing_manifest_is_empty(tmp_path: Path) -> None:
    library = StickerLibrary(root=tmp_path / "stickers", manifest_path=tmp_path / "none.yaml")

    assert library.select(tags=["reply"], random_value=0) is None
```

- [ ] **Step 2: Run sticker tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_stickers.py -q
```

Expected: FAIL with missing `qq_rolebot.stickers`.

- [ ] **Step 3: Implement sticker library**

Create `qq_rolebot/stickers.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StickerItem:
    id: str
    path: Path
    tags: tuple[str, ...]
    weight: int = 1


class StickerLibrary:
    def __init__(self, *, root: Path, manifest_path: Path) -> None:
        self.root = root
        self.manifest_path = manifest_path
        self._items: list[StickerItem] | None = None

    def select(self, *, tags: list[str], random_value: int) -> StickerItem | None:
        items = self._matching_items(tags)
        if not items:
            return None
        total = sum(item.weight for item in items)
        if total <= 0:
            return None
        cursor = random_value % total
        for item in items:
            if cursor < item.weight:
                return item
            cursor -= item.weight
        return items[-1]

    def _matching_items(self, tags: list[str]) -> list[StickerItem]:
        wanted = {tag.strip().lower() for tag in tags if tag.strip()}
        items = self._load_items()
        if not wanted:
            return items
        return [item for item in items if wanted.intersection(item.tags)]

    def _load_items(self) -> list[StickerItem]:
        if self._items is not None:
            return self._items
        self._items = self._read_items()
        return self._items

    def _read_items(self) -> list[StickerItem]:
        if not self.manifest_path.exists():
            return []
        raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        raw_items = raw.get("items", []) if isinstance(raw, dict) else []
        items: list[StickerItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = self._parse_item(raw_item)
            if item is not None:
                items.append(item)
        return items

    def _parse_item(self, raw_item: dict[str, Any]) -> StickerItem | None:
        item_id = str(raw_item.get("id", "") or "").strip()
        relative_file = str(raw_item.get("file", "") or "").strip()
        if not item_id or not relative_file:
            return None
        path = self.root / relative_file
        if not path.is_file():
            return None
        raw_tags = raw_item.get("tags", [])
        tags = tuple(
            str(tag).strip().lower()
            for tag in raw_tags
            if str(tag).strip()
        )
        try:
            weight = int(raw_item.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1
        return StickerItem(id=item_id, path=path, tags=tags, weight=max(1, weight))
```

- [ ] **Step 4: Run sticker tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_stickers.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/stickers.py tests/test_stickers.py
git commit -m "feat: load persistent sticker manifest"
```

---

### Task 4: Extract Repeat-Capable Media From Incoming Segments

**Files:**
- Modify: `qq_rolebot/message_segments.py`
- Modify: `qq_rolebot/policy.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_message_segments.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write message segment tests**

Append to `tests/test_message_segments.py`:

```python
def test_extract_repeat_media_prefers_face_id() -> None:
    message = [segment("face", id="14")]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "face"
    assert media.face_id == "14"
    assert media.signature == "face:14"


def test_extract_repeat_media_reads_image_file_or_url() -> None:
    message = [segment("image", file="abc.image", url="https://example.test/a.jpg")]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "image"
    assert media.file == "abc.image"
    assert media.url == "https://example.test/a.jpg"
    assert media.signature == "image:abc.image"
```

- [ ] **Step 2: Run segment tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_message_segments.py::test_extract_repeat_media_prefers_face_id tests/test_message_segments.py::test_extract_repeat_media_reads_image_file_or_url -q
```

Expected: FAIL with missing `extract_repeat_media`.

- [ ] **Step 3: Implement repeat media extraction**

In `qq_rolebot/message_segments.py`, add:

```python
@dataclass(frozen=True)
class RepeatMedia:
    kind: str = ""
    file: str = ""
    url: str = ""
    face_id: str = ""

    @property
    def signature(self) -> str:
        if self.kind == "face" and self.face_id:
            return f"face:{self.face_id}"
        if self.kind == "image":
            value = self.file or self.url
            return f"image:{value}" if value else ""
        return ""
```

Add after `extract_media_urls`:

```python
def extract_repeat_media(message: Iterable[Any]) -> RepeatMedia:
    for segment in message:
        if _segment_type(segment) != "face":
            continue
        face_id = _first_value(_data(segment), ("id",))
        if face_id:
            return RepeatMedia(kind="face", face_id=face_id)
    for segment in message:
        if _segment_type(segment) != "image":
            continue
        data = _data(segment)
        file_value = _first_value(data, ("file",))
        url_value = _first_value(data, ("url",))
        if file_value or url_value:
            return RepeatMedia(kind="image", file=file_value, url=url_value)
    return RepeatMedia()
```

- [ ] **Step 4: Add repeat media fields to IncomingMessage**

In `qq_rolebot/policy.py`, add to `IncomingMessage`:

```python
    repeat_media_kind: str = ""
    repeat_media_file: str = ""
    repeat_media_url: str = ""
    repeat_media_face_id: str = ""
    repeat_signature: str = ""
```

- [ ] **Step 5: Write plugin incoming test**

Append to `tests/test_plugin_smoke.py`:

```python
def test_plugin_extracts_repeat_face_metadata(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=False,
        message=[SimpleNamespace(type="face", data={"id": "14"})],
        get_plaintext=lambda: "",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming is not None
    assert incoming.repeat_media_kind == "face"
    assert incoming.repeat_media_face_id == "14"
    assert incoming.repeat_signature == "face:14"
```

- [ ] **Step 6: Update plugin message construction**

In `qq_rolebot/plugins/roleplay_chat.py`, import:

```python
    extract_repeat_media,
```

Inside `build_incoming_message`, after `media_urls = extract_media_urls(message_segments)`:

```python
    repeat_media = extract_repeat_media(message_segments)
```

When constructing both private and group `IncomingMessage`, add:

```python
            repeat_media_kind=repeat_media.kind,
            repeat_media_file=repeat_media.file,
            repeat_media_url=repeat_media.url,
            repeat_media_face_id=repeat_media.face_id,
            repeat_signature=repeat_media.signature,
```

- [ ] **Step 7: Run segment and plugin tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_message_segments.py tests/test_plugin_smoke.py::test_plugin_extracts_repeat_face_metadata -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add qq_rolebot/message_segments.py qq_rolebot/policy.py qq_rolebot/plugins/roleplay_chat.py tests/test_message_segments.py tests/test_plugin_smoke.py
git commit -m "feat: extract repeat media metadata"
```

---

### Task 5: Add In-Process Repeat Policy For Text, Image, And Face

**Files:**
- Create: `qq_rolebot/repeat_policy.py`
- Test: `tests/test_repeat_policy.py`

- [ ] **Step 1: Write repeat policy tests**

Create `tests/test_repeat_policy.py`:

```python
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.repeat_policy import RepeatTracker


def msg(
    text: str,
    *,
    sender: int,
    created_at: int,
    repeat_signature: str = "",
    media_kind: str = "",
    media_file: str = "",
    media_url: str = "",
    face_id: str = "",
) -> IncomingMessage:
    return IncomingMessage(
        group_id=20,
        user_id=sender,
        nickname=f"user-{sender}",
        text=text,
        is_at_bot=False,
        created_at=created_at,
        repeat_signature=repeat_signature,
        repeat_media_kind=media_kind,
        repeat_media_file=media_file,
        repeat_media_url=media_url,
        repeat_media_face_id=face_id,
    )


def test_repeat_tracker_repeats_text_after_two_users() -> None:
    tracker = RepeatTracker(threshold=2)

    assert tracker.record_and_match(msg("好耶", sender=1, created_at=100), now=100) is None
    reply = tracker.record_and_match(msg("好耶", sender=2, created_at=101), now=101)

    assert reply is not None
    assert reply.source == "repeat"
    assert reply.messages[0].kind == "text"
    assert reply.messages[0].text == "好耶"


def test_repeat_tracker_repeats_image_without_persisting_file() -> None:
    tracker = RepeatTracker(threshold=2)
    first = msg(
        "[image: a.jpg]",
        sender=1,
        created_at=100,
        repeat_signature="image:a.jpg",
        media_kind="image",
        media_file="a.jpg",
    )
    second = msg(
        "[image: a.jpg]",
        sender=2,
        created_at=101,
        repeat_signature="image:a.jpg",
        media_kind="image",
        media_file="a.jpg",
    )

    assert tracker.record_and_match(first, now=100) is None
    reply = tracker.record_and_match(second, now=101)

    assert reply is not None
    assert reply.messages[0].kind == "image"
    assert reply.messages[0].file == "a.jpg"


def test_repeat_tracker_repeats_face() -> None:
    tracker = RepeatTracker(threshold=2)

    tracker.record_and_match(
        msg("[emoji: 14]", sender=1, created_at=100, repeat_signature="face:14", media_kind="face", face_id="14"),
        now=100,
    )
    reply = tracker.record_and_match(
        msg("[emoji: 14]", sender=2, created_at=101, repeat_signature="face:14", media_kind="face", face_id="14"),
        now=101,
    )

    assert reply is not None
    assert reply.messages[0].kind == "face"
    assert reply.messages[0].face_id == "14"


def test_repeat_tracker_cools_down_same_signature() -> None:
    tracker = RepeatTracker(threshold=2, cooldown_seconds=600)

    tracker.record_and_match(msg("好耶", sender=1, created_at=100), now=100)
    assert tracker.record_and_match(msg("好耶", sender=2, created_at=101), now=101) is not None
    assert tracker.record_and_match(msg("好耶", sender=3, created_at=200), now=200) is None
    assert tracker.record_and_match(msg("好耶", sender=4, created_at=701), now=701) is not None
```

- [ ] **Step 2: Run repeat policy tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_repeat_policy.py -q
```

Expected: FAIL with missing `qq_rolebot.repeat_policy`.

- [ ] **Step 3: Implement repeat tracker**

Create `qq_rolebot/repeat_policy.py`:

```python
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
from qq_rolebot.policy import IncomingMessage


@dataclass(frozen=True)
class RepeatEntry:
    group_id: int
    user_id: int
    signature: str
    text: str
    created_at: int
    media_kind: str = ""
    media_file: str = ""
    media_url: str = ""
    media_face_id: str = ""


class RepeatTracker:
    def __init__(
        self,
        *,
        threshold: int,
        cooldown_seconds: int = 600,
        window_seconds: int = 600,
    ) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds
        self._entries: dict[int, deque[RepeatEntry]] = defaultdict(deque)
        self._cooldowns: dict[tuple[int, str], int] = {}

    def record_and_match(self, message: IncomingMessage, *, now: int) -> OutgoingReply | None:
        entry = self._entry(message)
        if entry is None:
            return None
        entries = self._entries[message.group_id]
        entries.append(entry)
        self._prune(message.group_id, now=now)
        if len(entries) < self.threshold:
            return None
        tail = list(entries)[-self.threshold:]
        if any(item.signature != entry.signature for item in tail):
            return None
        if len({item.user_id for item in tail}) < 2:
            return None
        cooldown_key = (message.group_id, entry.signature)
        last_reply_at = self._cooldowns.get(cooldown_key)
        if last_reply_at is not None and now - last_reply_at < self.cooldown_seconds:
            return None
        reply = self._reply(entry)
        if reply is None:
            return None
        self._cooldowns[cooldown_key] = now
        return reply

    def _entry(self, message: IncomingMessage) -> RepeatEntry | None:
        signature = message.repeat_signature.strip() or self._text_signature(message.text)
        if not signature:
            return None
        return RepeatEntry(
            group_id=message.group_id,
            user_id=message.user_id,
            signature=signature,
            text=message.text.strip(),
            created_at=message.created_at,
            media_kind=message.repeat_media_kind,
            media_file=message.repeat_media_file,
            media_url=message.repeat_media_url,
            media_face_id=message.repeat_media_face_id,
        )

    @staticmethod
    def _text_signature(text: str) -> str:
        compact = text.strip()
        return f"text:{compact}" if compact else ""

    @staticmethod
    def _reply(entry: RepeatEntry) -> OutgoingReply | None:
        if entry.media_kind == "image":
            value = entry.media_file or entry.media_url
            if value:
                return OutgoingReply(
                    source="repeat",
                    messages=[OutgoingMessage(kind="image", file=value, source="repeat")],
                )
        if entry.media_kind == "face" and entry.media_face_id:
            return OutgoingReply(
                source="repeat",
                messages=[OutgoingMessage(kind="face", face_id=entry.media_face_id, source="repeat")],
            )
        if entry.text:
            return OutgoingReply.text(entry.text, source="repeat")
        return None

    def _prune(self, group_id: int, *, now: int) -> None:
        entries = self._entries[group_id]
        while entries and now - entries[0].created_at > self.window_seconds:
            entries.popleft()
```

- [ ] **Step 4: Run repeat policy tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_repeat_policy.py -q
```

Expected: PASS.

- [ ] **Step 5: Run repeat-related tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_repeat_policy.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add qq_rolebot/repeat_policy.py tests/test_repeat_policy.py
git commit -m "feat: track repeat media in memory"
```

---

### Task 6: Migrate ChatService To OutgoingReply And AgentRunner

**Files:**
- Create: `qq_rolebot/agent_runner.py`
- Modify: `qq_rolebot/service.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_agent_runner.py`
- Test: `tests/test_service.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write agent runner tests**

Create `tests/test_agent_runner.py`:

```python
from pathlib import Path

import pytest

from qq_rolebot.agent_runner import AgentRunner
from qq_rolebot.config import load_settings
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.storage import MessageRecord


class FakeModel:
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        assert messages
        return ModelResult(ok=True, text=" model reply ")


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
    }


@pytest.mark.asyncio
async def test_agent_runner_returns_clean_text(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    runner = AgentRunner(settings=settings, model=FakeModel())
    message = IncomingMessage(
        group_id=20,
        user_id=11,
        nickname="Amy",
        text="hello",
        is_at_bot=True,
        created_at=100,
    )

    result = await runner.run(
        persona=load_persona(settings.persona_path),
        context=[MessageRecord(20, 11, "Amy", "hello", 100)],
        message=message,
        tool_context="",
    )

    assert result.ok is True
    assert result.text == "model reply"
```

- [ ] **Step 2: Run agent runner test and verify it fails**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_agent_runner.py -q
```

Expected: FAIL with missing `qq_rolebot.agent_runner`.

- [ ] **Step 3: Implement AgentRunner**

Create `qq_rolebot/agent_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qq_rolebot.config import Settings
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import Persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.storage import MessageRecord


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        ...


@dataclass(frozen=True)
class AgentRunResult:
    ok: bool
    text: str = ""
    error: str = ""


class AgentRunner:
    def __init__(self, *, settings: Settings, model: ChatModel) -> None:
        self.settings = settings
        self.model = model

    async def run(
        self,
        *,
        persona: Persona,
        context: list[MessageRecord],
        message: IncomingMessage,
        tool_context: str,
    ) -> AgentRunResult:
        messages = build_chat_messages(persona, context, message, tool_context=tool_context)
        result = await self.model.chat(messages)
        if not result.ok:
            return AgentRunResult(ok=False, error=result.error)
        text = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if text is None:
            return AgentRunResult(ok=False, error="guardrails rejected response")
        return AgentRunResult(ok=True, text=text)
```

- [ ] **Step 4: Run agent runner tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_agent_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Convert ChatService to `handle_reply`**

Append the service image repeat test to `tests/test_service.py` first:

```python
@pytest.mark.asyncio
async def test_service_handle_reply_repeats_image_without_model(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    model = CountingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
    )

    first = IncomingMessage(
        group_id=20,
        user_id=11,
        nickname="Amy",
        text="[image: a.jpg]",
        is_at_bot=False,
        created_at=100,
        repeat_media_kind="image",
        repeat_media_file="a.jpg",
        repeat_signature="image:a.jpg",
    )
    second = IncomingMessage(
        group_id=20,
        user_id=12,
        nickname="Bob",
        text="[image: a.jpg]",
        is_at_bot=False,
        created_at=101,
        repeat_media_kind="image",
        repeat_media_file="a.jpg",
        repeat_signature="image:a.jpg",
    )

    assert await service.handle_reply(first, random_value=99) is None
    reply = await service.handle_reply(second, random_value=99)

    assert reply is not None
    assert reply.messages[0].kind == "image"
    assert reply.messages[0].file == "a.jpg"
    assert model.calls == 0
```

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_service.py::test_service_handle_reply_repeats_image_without_model -q
```

Expected: FAIL with missing `ChatService.handle_reply` or text-only repeat behavior.

In `qq_rolebot/service.py`:

1. Import `AgentRunner`, `OutgoingReply`, and `RepeatTracker`.
2. In `__init__`, set:

```python
        self.agent_runner = AgentRunner(settings=settings, model=model)
        self.repeat_tracker = RepeatTracker(
            threshold=settings.repeat_reply_threshold,
            cooldown_seconds=REPEAT_REPLY_COOLDOWN_SECONDS,
            window_seconds=settings.context_window_seconds,
        )
        self.reply_enhancer = None
```

3. Change `handle` to compatibility wrapper:

```python
    async def handle(self, message: IncomingMessage, *, random_value: int) -> str | None:
        reply = await self.handle_reply(message, random_value=random_value)
        return reply.text if reply is not None else None
```

4. Rename the old `handle` body to `handle_reply` and change successful returns:

```python
return OutgoingReply.text(reply, source="admin")
return repeat_reply_obj
return OutgoingReply.text(reply, source="tool")
return OutgoingReply.text(result_text, source="model")
```

5. Replace the old `_repeat_reply(...)` call with:

```python
        if self.settings.repeat_reply_enabled and group.enabled:
            if group.muted_until <= message.created_at and not (
                message.is_at_bot or message.is_reply_to_bot
            ):
                repeat_reply = self.repeat_tracker.record_and_match(
                    message,
                    now=message.created_at,
                )
                if repeat_reply is not None:
                    repeat_text = repeat_reply.text or message.text
                    await self._save_bot_reply(
                        group_id=message.group_id,
                        reply=repeat_text,
                        created_at=message.created_at,
                    )
                    self._trace(
                        trace,
                        "reply.final",
                        {"reply": repeat_text, "source": "repeat"},
                    )
                    return repeat_reply
```

6. Replace inline model calls with:

```python
        agent_result = await self.agent_runner.run(
            persona=self.persona,
            context=context,
            message=message,
            tool_context=tool_context,
        )
        if not agent_result.ok:
            self._trace(trace, "reply.final", {"reply": None, "source": "model_error"})
            return None

        reply = agent_result.text
```

Apply the same pattern in private handling by adding `_handle_private_reply` that returns
`OutgoingReply | None`. Keep `_handle_private` as this text wrapper:

```python
    async def _handle_private(
        self,
        message: IncomingMessage,
        *,
        trace: DebugTrace | None,
    ) -> str | None:
        reply = await self._handle_private_reply(message, trace=trace, random_value=100)
        return reply.text if reply is not None else None
```

- [ ] **Step 6: Update plugin to call `handle_reply` and renderer**

In `qq_rolebot/plugins/roleplay_chat.py`, replace:

```python
    reply = await service.handle(incoming, random_value=random.randrange(100))
    if reply:
```

with:

```python
    outgoing_reply = await service.handle_reply(incoming, random_value=random.randrange(100))
    if outgoing_reply is not None and not outgoing_reply.is_empty:
```

Keep TTS conservative:

```python
        text_reply = outgoing_reply.text
        if text_reply and voice_service is not None:
            voice = await voice_service.maybe_render(incoming, reply=text_reply)
            if voice.file_path is not None:
                await bot.send(event, MessageSegment.record(str(voice.file_path)))
                return
        await send_outgoing_reply(bot, event, outgoing_reply)
```

- [ ] **Step 7: Run service and plugin tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_agent_runner.py tests/test_service.py tests/test_plugin_smoke.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add qq_rolebot/agent_runner.py qq_rolebot/service.py qq_rolebot/plugins/roleplay_chat.py tests/test_agent_runner.py tests/test_service.py tests/test_plugin_smoke.py
git commit -m "feat: route replies through controlled agent pipeline"
```

---

### Task 7: Add ReplyEnhancer For Active Sticker Append

**Files:**
- Create: `qq_rolebot/reply_enhancer.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Modify: `qq_rolebot/service.py`
- Test: `tests/test_reply_enhancer.py`
- Test: `tests/test_service.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write reply enhancer tests**

Create `tests/test_reply_enhancer.py`:

```python
from pathlib import Path

from qq_rolebot.outgoing import OutgoingReply
from qq_rolebot.reply_enhancer import ReplyEnhancer
from qq_rolebot.stickers import StickerLibrary


def build_library(tmp_path: Path) -> StickerLibrary:
    root = tmp_path / "stickers"
    (root / "chongyue").mkdir(parents=True)
    (root / "chongyue" / "calm.webp").write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: calm
    file: chongyue/calm.webp
    tags: [reply]
    weight: 1
""".strip(),
        encoding="utf-8",
    )
    return StickerLibrary(root=root, manifest_path=manifest)


def test_reply_enhancer_appends_sticker_after_text(tmp_path: Path) -> None:
    enhancer = ReplyEnhancer(enabled=True, probability=100, library=build_library(tmp_path))

    reply = enhancer.enhance(OutgoingReply.text("一切安好。", source="model"), random_value=0)

    assert [message.kind for message in reply.messages] == ["text", "image"]
    assert reply.messages[1].source == "sticker"


def test_reply_enhancer_never_creates_standalone_reply(tmp_path: Path) -> None:
    enhancer = ReplyEnhancer(enabled=True, probability=100, library=build_library(tmp_path))

    reply = enhancer.enhance(OutgoingReply(source="model", messages=[]), random_value=0)

    assert reply.messages == []
```

- [ ] **Step 2: Run enhancer tests and verify they fail**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_reply_enhancer.py -q
```

Expected: FAIL with missing `qq_rolebot.reply_enhancer`.

- [ ] **Step 3: Implement ReplyEnhancer**

Create `qq_rolebot/reply_enhancer.py`:

```python
from __future__ import annotations

from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
from qq_rolebot.stickers import StickerLibrary


class ReplyEnhancer:
    def __init__(
        self,
        *,
        enabled: bool,
        probability: int,
        library: StickerLibrary | None,
    ) -> None:
        self.enabled = enabled
        self.probability = probability
        self.library = library

    def enhance(self, reply: OutgoingReply, *, random_value: int) -> OutgoingReply:
        if not self.enabled or self.library is None:
            return reply
        if reply.is_empty or not reply.text.strip():
            return reply
        if self.probability <= 0 or random_value >= self.probability:
            return reply
        item = self.library.select(tags=["reply"], random_value=random_value)
        if item is None:
            return reply
        return reply.with_message(
            OutgoingMessage(kind="image", file=str(item.path), source="sticker")
        )
```

- [ ] **Step 4: Wire enhancer in plugin construction**

In `qq_rolebot/plugins/roleplay_chat.py`, import:

```python
from qq_rolebot.reply_enhancer import ReplyEnhancer
from qq_rolebot.stickers import StickerLibrary
```

Build after `service = ChatService(...)`:

```python
sticker_library = StickerLibrary(
    root=settings.media_sticker_root,
    manifest_path=settings.media_sticker_manifest,
)
reply_enhancer = ReplyEnhancer(
    enabled=settings.media_reply_enabled,
    probability=settings.media_reply_probability,
    library=sticker_library,
)
service.reply_enhancer = reply_enhancer
```

In `ChatService.__init__`, add:

```python
        self.reply_enhancer = None
```

After model `OutgoingReply.text(reply, source="model")` is constructed:

```python
        outgoing = OutgoingReply.text(reply, source="model")
        if self.reply_enhancer is not None:
            outgoing = self.reply_enhancer.enhance(outgoing, random_value=random_value)
        return outgoing
```

Do not run enhancer for admin, tool direct replies, or repeat replies in the first implementation.

- [ ] **Step 5: Write service active sticker test**

Append to `tests/test_service.py`:

```python
@pytest.mark.asyncio
async def test_service_appends_sticker_only_after_model_reply(tmp_path: Path) -> None:
    raw_env = env(tmp_path)
    raw_env["MEDIA_REPLY_ENABLED"] = "true"
    raw_env["MEDIA_REPLY_PROBABILITY"] = "100"
    settings = load_settings(raw_env)
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    class FakeEnhancer:
        def enhance(self, reply, *, random_value: int):
            from qq_rolebot.outgoing import OutgoingMessage

            return reply.with_message(OutgoingMessage(kind="image", file="calm.webp", source="sticker"))

    service.reply_enhancer = FakeEnhancer()

    reply = await service.handle_reply(msg("hello", at_bot=True), random_value=0)

    assert reply is not None
    assert [message.kind for message in reply.messages] == ["text", "image"]
```

- [ ] **Step 6: Run enhancer and service tests**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_reply_enhancer.py tests/test_service.py::test_service_appends_sticker_only_after_model_reply -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add qq_rolebot/reply_enhancer.py qq_rolebot/stickers.py qq_rolebot/service.py qq_rolebot/plugins/roleplay_chat.py tests/test_reply_enhancer.py tests/test_service.py
git commit -m "feat: append persistent stickers after model replies"
```

---

### Task 8: Update Deployment And Documentation

**Files:**
- Modify: `scripts/deploy_server.sh`
- Modify: `tests/test_deploy_script.py`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `.gitignore`

- [ ] **Step 1: Write deploy script test**

Append to `tests/test_deploy_script.py`:

```python
def test_deploy_script_preserves_stickers_directory() -> None:
    script = Path("scripts/deploy_server.sh").read_text(encoding="utf-8")

    assert "stickers" in script
    assert "voice_cache models stickers" in script
```

- [ ] **Step 2: Run deploy test and verify it fails**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_deploy_script.py::test_deploy_script_preserves_stickers_directory -q
```

Expected: FAIL because `stickers` is not preserved.

- [ ] **Step 3: Preserve sticker directory in deploy script**

In `scripts/deploy_server.sh`, change both runtime directory lists:

```bash
  for runtime_dir in data voice_refs voice_cache models stickers; do
```

and both `git clean` lines:

```bash
    git clean -fd -e .env -e .watchdog.env -e data/ -e voice_refs/ -e voice_cache/ -e models/ -e stickers/
```

- [ ] **Step 4: Update docs**

In `.gitignore`, add:

```gitignore
stickers/
!stickers/example-manifest.yaml
```

In `README.md`, add media settings near the runtime config list:

```markdown
- `MEDIA_REPLY_ENABLED`: whether successful model text replies may append a persistent sticker image.
- `MEDIA_REPLY_PROBABILITY`: `0` to `100`; chance to append a sticker after model text.
- `MEDIA_STICKER_ROOT`: persistent sticker asset directory. Production default should be `/opt/qq-rolebot/stickers`.
- `MEDIA_STICKER_MANIFEST`: optional manifest path; defaults to `MEDIA_STICKER_ROOT/manifest.yaml`.
```

In `docs/deployment.md`, add `/opt/qq-rolebot/stickers` to the server layout and note:

```markdown
Store production sticker images and `manifest.yaml` under `/opt/qq-rolebot/stickers`. The deploy
script preserves this directory. Do not commit real sticker packs or generated media to git.
```

- [ ] **Step 5: Run docs and deploy checks**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_deploy_script.py -q
git diff --check
```

Expected: PASS and no `git diff --check` output.

- [ ] **Step 6: Commit**

```bash
git add scripts/deploy_server.sh tests/test_deploy_script.py README.md docs/deployment.md .gitignore
git commit -m "docs: document persistent sticker assets"
```

---

### Task 9: Final Verification

**Files:**
- All files changed by prior tasks.

- [ ] **Step 1: Run ruff**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
```

Expected: exit 0.

- [ ] **Step 2: Run full test suite**

Run:

```bash
~/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Inspect branch summary**

Run:

```bash
git status --short --untracked-files=all
git log --oneline --decorate --max-count=8
```

Expected: working tree clean; latest commits are on `feature/controlled-agent-media-pipeline`.

- [ ] **Step 5: Report verification evidence**

Summarize the exact commands and results in the final implementation response. Do not push unless
the user explicitly asks.
