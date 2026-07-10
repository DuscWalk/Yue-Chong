# Custom Face And Repeat Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register active image assets as QQ custom faces when possible, and make repeat (`+1`) preserve text, image, face, and marketplace sticker formats.

**Architecture:** Extend the existing transport-neutral `OutgoingReply` model with `mface`, teach incoming parsing to preserve marketplace sticker metadata, and keep local custom-face registration as an account-side maintenance path with image fallback. Active sticker selection prefers sendable `mface` metadata only when a manifest item contains complete marketplace fields; locally registered image assets remain sendable as ordinary images because NapCat's `mface` path is for marketplace stickers.

**Tech Stack:** Python 3.11, NoneBot2 OneBot v11 `MessageSegment`, NapCat OneBot APIs `add_custom_face` and `fetch_custom_face_detail`, pytest, ruff.

---

## File Map

- Modify `qq_rolebot/outgoing.py`: add `mface` fields to `OutgoingMessage`.
- Modify `qq_rolebot/plugins/roleplay_chat.py`: render `mface`, register active library images after bot connection.
- Modify `qq_rolebot/message_segments.py`: extract marketplace sticker metadata from `mface` segments and NapCat special image segments.
- Modify `qq_rolebot/repeat_policy.py`: store and repeat `mface` metadata.
- Modify `qq_rolebot/stickers.py`: parse manifest `type` and optional sendable `mface` fields.
- Modify `qq_rolebot/reply_enhancer.py`: prefer sendable `mface`, otherwise image fallback.
- Create `qq_rolebot/custom_faces.py`: register local image assets with NapCat and maintain a server-side JSON cache.
- Modify `qq_rolebot/config.py`, `.env.example`, `README.md`, `docs/deployment.md`: document registration cache and switch.
- Add and update tests in `tests/test_outgoing.py`, `tests/test_plugin_smoke.py`, `tests/test_message_segments.py`, `tests/test_repeat_policy.py`, `tests/test_stickers.py`, `tests/test_reply_enhancer.py`, `tests/test_custom_faces.py`, `tests/test_config.py`.

---

### Task 1: Add Transport-Neutral `mface` Output

**Files:**
- Modify: `qq_rolebot/outgoing.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_outgoing.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing outgoing tests**

Add to `tests/test_outgoing.py`:

```python
def test_outgoing_mface_is_not_empty() -> None:
    message = OutgoingMessage(
        kind="mface",
        emoji_id="123",
        emoji_package_id="456",
        key="send-key",
        summary="[测试表情]",
        source="repeat",
    )

    assert message.is_empty is False


def test_outgoing_mface_requires_send_fields() -> None:
    assert OutgoingMessage(kind="mface", emoji_id="123").is_empty is True
```

Add to `tests/test_plugin_smoke.py`:

```python
def test_render_outgoing_message_renders_mface(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")

    segment = module.render_outgoing_message(
        module.OutgoingMessage(
            kind="mface",
            emoji_id="123",
            emoji_package_id="456",
            key="send-key",
            summary="[测试表情]",
            source="repeat",
        )
    )

    assert segment is not None
    assert segment.type == "mface"
    assert segment.data == {
        "emoji_id": "123",
        "emoji_package_id": 456,
        "key": "send-key",
        "summary": "[测试表情]",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_outgoing.py::test_outgoing_mface_is_not_empty tests/test_outgoing.py::test_outgoing_mface_requires_send_fields tests/test_plugin_smoke.py::test_render_outgoing_message_renders_mface -q
```

Expected: fail because `OutgoingKind` does not allow `mface`, `OutgoingMessage` has no mface fields, and the renderer returns `None`.

- [ ] **Step 3: Implement minimal `mface` model and renderer**

In `qq_rolebot/outgoing.py`, change:

```python
OutgoingKind = Literal["text", "image", "face", "mface", "record"]
```

Add fields to `OutgoingMessage`:

```python
    emoji_id: str = ""
    emoji_package_id: str = ""
    key: str = ""
    summary: str = ""
```

Add to `is_empty`:

```python
        if self.kind == "mface":
            return not (
                self.emoji_id.strip()
                and self.emoji_package_id.strip()
                and self.key.strip()
                and self.summary.strip()
            )
```

In `qq_rolebot/plugins/roleplay_chat.py`, add before `record` handling:

```python
    if message.kind == "mface" and not message.is_empty:
        return MessageSegment(
            "mface",
            {
                "emoji_id": message.emoji_id.strip(),
                "emoji_package_id": int(message.emoji_package_id),
                "key": message.key.strip(),
                "summary": message.summary.strip(),
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2. Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/outgoing.py qq_rolebot/plugins/roleplay_chat.py tests/test_outgoing.py tests/test_plugin_smoke.py
git commit -m "feat: render mface outgoing messages"
```

---

### Task 2: Extract Marketplace Sticker Metadata From Incoming Messages

**Files:**
- Modify: `qq_rolebot/message_segments.py`
- Test: `tests/test_message_segments.py`

- [ ] **Step 1: Write failing extraction tests**

Add to `tests/test_message_segments.py`:

```python
def test_extract_repeat_media_reads_mface_segment() -> None:
    message = [
        segment(
            "mface",
            emoji_id="123",
            emoji_package_id=456,
            key="send-key",
            summary="[测试表情]",
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "mface"
    assert media.emoji_id == "123"
    assert media.emoji_package_id == "456"
    assert media.key == "send-key"
    assert media.summary == "[测试表情]"
    assert media.signature == "mface:456:123:send-key"


def test_extract_repeat_media_reads_marketface_image_segment() -> None:
    message = [
        segment(
            "image",
            file="ab-123.gif",
            url="https://example.test/ab-123.gif",
            emoji_id="123",
            emoji_package_id=456,
            key="send-key",
            summary="[商城表情]",
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "mface"
    assert media.file == "ab-123.gif"
    assert media.url == "https://example.test/ab-123.gif"
    assert media.signature == "mface:456:123:send-key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_message_segments.py::test_extract_repeat_media_reads_mface_segment tests/test_message_segments.py::test_extract_repeat_media_reads_marketface_image_segment -q
```

Expected: fail because `RepeatMedia` does not expose mface fields and `extract_repeat_media` returns image or empty.

- [ ] **Step 3: Implement mface extraction**

In `RepeatMedia`, add:

```python
    emoji_id: str = ""
    emoji_package_id: str = ""
    key: str = ""
    summary: str = ""
```

Change `signature`:

```python
        if self.kind == "mface" and self.emoji_id and self.emoji_package_id and self.key:
            return f"mface:{self.emoji_package_id}:{self.emoji_id}:{self.key}"
```

Add helper:

```python
def _mface_from_data(data: dict[str, Any], *, file_value: str = "", url_value: str = "") -> RepeatMedia | None:
    emoji_id = _first_value(data, ("emoji_id", "emojiId", "emoId"))
    emoji_package_id = _first_value(data, ("emoji_package_id", "emojiPackageId", "epId"))
    key = _first_value(data, ("key",))
    summary = _first_value(data, ("summary", "faceName", "desc")) or "[商城表情]"
    if emoji_id and emoji_package_id and key:
        return RepeatMedia(
            kind="mface",
            file=file_value,
            url=url_value,
            emoji_id=emoji_id,
            emoji_package_id=emoji_package_id,
            key=key,
            summary=summary,
        )
    return None
```

Update `extract_repeat_media` to check `mface` segments before `face`, and to check image data for mface fields before returning ordinary image.

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2. Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/message_segments.py tests/test_message_segments.py
git commit -m "feat: extract mface repeat metadata"
```

---

### Task 3: Repeat `mface` In The +1 Path

**Files:**
- Modify: `qq_rolebot/policy.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Modify: `qq_rolebot/repeat_policy.py`
- Test: `tests/test_repeat_policy.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing repeat tests**

Update the helper `msg` in `tests/test_repeat_policy.py` to accept:

```python
    emoji_id: str = "",
    emoji_package_id: str = "",
    key: str = "",
    summary: str = "",
```

and pass these into `IncomingMessage`.

Add:

```python
def test_repeat_tracker_repeats_mface() -> None:
    tracker = RepeatTracker(threshold=2)
    kwargs = {
        "repeat_signature": "mface:456:123:send-key",
        "media_kind": "mface",
        "emoji_id": "123",
        "emoji_package_id": "456",
        "key": "send-key",
        "summary": "[测试表情]",
    }

    tracker.record_and_match(msg("[测试表情]", sender=1, created_at=100, **kwargs), now=100)
    reply = tracker.record_and_match(
        msg("[测试表情]", sender=2, created_at=101, **kwargs),
        now=101,
    )

    assert reply is not None
    assert reply.messages[0].kind == "mface"
    assert reply.messages[0].emoji_id == "123"
    assert reply.messages[0].emoji_package_id == "456"
    assert reply.messages[0].key == "send-key"
    assert reply.messages[0].summary == "[测试表情]"
```

Add to `tests/test_plugin_smoke.py`:

```python
def test_plugin_builds_incoming_message_with_mface_repeat_metadata(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        to_me=False,
        message=[
            SimpleNamespace(
                type="image",
                data={
                    "file": "ab-123.gif",
                    "url": "https://example.test/ab-123.gif",
                    "emoji_id": "123",
                    "emoji_package_id": 456,
                    "key": "send-key",
                    "summary": "[商城表情]",
                },
            )
        ],
        get_plaintext=lambda: "",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming is not None
    assert incoming.repeat_media_kind == "mface"
    assert incoming.repeat_signature == "mface:456:123:send-key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_repeat_policy.py::test_repeat_tracker_repeats_mface tests/test_plugin_smoke.py::test_plugin_builds_incoming_message_with_mface_repeat_metadata -q
```

Expected: fail because `IncomingMessage` lacks mface fields and `RepeatTracker` does not return mface messages.

- [ ] **Step 3: Implement mface repeat plumbing**

In `IncomingMessage` in `qq_rolebot/policy.py`, add default fields:

```python
    repeat_media_emoji_id: str = ""
    repeat_media_emoji_package_id: str = ""
    repeat_media_key: str = ""
    repeat_media_summary: str = ""
```

In both `IncomingMessage` construction branches in `qq_rolebot/plugins/roleplay_chat.py`, pass the matching `repeat_media` fields.

In `RepeatEntry` in `qq_rolebot/repeat_policy.py`, add the same four fields. Store them in `_entry`.

In `_reply`, add:

```python
        if entry.media_kind == "mface":
            if entry.media_emoji_id and entry.media_emoji_package_id and entry.media_key:
                return OutgoingReply(
                    source="repeat",
                    messages=[
                        OutgoingMessage(
                            kind="mface",
                            emoji_id=entry.media_emoji_id,
                            emoji_package_id=entry.media_emoji_package_id,
                            key=entry.media_key,
                            summary=entry.media_summary or "[商城表情]",
                            source="repeat",
                        )
                    ],
                )
            value = entry.media_file or entry.media_url
            if value:
                return OutgoingReply(
                    source="repeat",
                    messages=[OutgoingMessage(kind="image", file=value, source="repeat")],
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2. Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/policy.py qq_rolebot/plugins/roleplay_chat.py qq_rolebot/repeat_policy.py tests/test_repeat_policy.py tests/test_plugin_smoke.py
git commit -m "feat: repeat mface messages"
```

---

### Task 4: Prefer Sendable Manifest `mface` For Active Stickers

**Files:**
- Modify: `qq_rolebot/stickers.py`
- Modify: `qq_rolebot/reply_enhancer.py`
- Test: `tests/test_stickers.py`
- Test: `tests/test_reply_enhancer.py`

- [ ] **Step 1: Write failing sticker tests**

Add to `tests/test_stickers.py`:

```python
def test_sticker_library_loads_mface_metadata(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    image = root / "market.webp"
    image.write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: market
    file: market.webp
    type: mface
    emoji_id: "123"
    emoji_package_id: "456"
    key: send-key
    summary: "[测试表情]"
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )

    item = StickerLibrary(root=root, manifest_path=manifest).select(
        tags=["reply"],
        random_value=0,
    )

    assert item is not None
    assert item.media_type == "mface"
    assert item.is_sendable_mface is True
    assert item.emoji_id == "123"
```

Add to `tests/test_reply_enhancer.py`:

```python
def test_reply_enhancer_prefers_sendable_mface(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    (root / "market.webp").write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: market
    file: market.webp
    type: mface
    emoji_id: "123"
    emoji_package_id: "456"
    key: send-key
    summary: "[测试表情]"
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )
    enhancer = ReplyEnhancer(
        enabled=True,
        probability=100,
        library=StickerLibrary(root=root, manifest_path=manifest),
    )

    reply = enhancer.enhance(OutgoingReply.text("一切安好。", source="model"), random_value=0)

    assert [message.kind for message in reply.messages] == ["text", "mface"]
    assert reply.messages[1].emoji_id == "123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_stickers.py::test_sticker_library_loads_mface_metadata tests/test_reply_enhancer.py::test_reply_enhancer_prefers_sendable_mface -q
```

Expected: fail because `StickerItem` has no media type or mface fields and `ReplyEnhancer` always appends image.

- [ ] **Step 3: Implement manifest mface support**

In `StickerItem`, add:

```python
    media_type: str = "image"
    emoji_id: str = ""
    emoji_package_id: str = ""
    key: str = ""
    summary: str = ""

    @property
    def is_sendable_mface(self) -> bool:
        return (
            self.media_type == "mface"
            and bool(self.emoji_id.strip())
            and bool(self.emoji_package_id.strip())
            and bool(self.key.strip())
            and bool(self.summary.strip())
        )
```

In `_parse_item`, read `type`, `emoji_id`, `emoji_package_id`, `key`, and `summary`; keep default `media_type="image"` for existing manifests.

In `ReplyEnhancer.enhance`, replace the appended image with:

```python
        if item.is_sendable_mface:
            return reply.with_message(
                OutgoingMessage(
                    kind="mface",
                    emoji_id=item.emoji_id,
                    emoji_package_id=item.emoji_package_id,
                    key=item.key,
                    summary=item.summary,
                    file=str(item.path),
                    source="sticker",
                )
            )
        return reply.with_message(
            OutgoingMessage(kind="image", file=str(item.path), source="sticker")
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2. Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/stickers.py qq_rolebot/reply_enhancer.py tests/test_stickers.py tests/test_reply_enhancer.py
git commit -m "feat: support sendable mface sticker assets"
```

---

### Task 5: Register Active Image Assets As Custom Faces

**Files:**
- Create: `qq_rolebot/custom_faces.py`
- Modify: `qq_rolebot/config.py`
- Modify: `qq_rolebot/stickers.py`
- Test: `tests/test_custom_faces.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing custom face tests**

Create `tests/test_custom_faces.py`:

```python
from pathlib import Path

from qq_rolebot.custom_faces import CustomFaceRegistrar
from qq_rolebot.stickers import StickerLibrary


class FakeCustomFaceClient:
    def __init__(self, details=None):
        self.added = []
        self.details = details or []

    async def add_custom_face(self, *, file: str, is_origin: bool = True):
        self.added.append((file, is_origin))
        return {"result": 0}

    async def fetch_custom_face_detail(self, *, count: int = 48):
        return self.details


def build_library(tmp_path: Path) -> StickerLibrary:
    root = tmp_path / "stickers"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"image-a")
    (root / "b.jpg").write_bytes(b"image-b")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: a
    file: a.jpg
    type: custom_face
    tags: [reply]
  - id: b
    file: b.jpg
    type: image
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )
    return StickerLibrary(root=root, manifest_path=manifest)


async def test_custom_face_registrar_adds_manifest_images_and_writes_cache(tmp_path: Path) -> None:
    client = FakeCustomFaceClient()
    cache_path = tmp_path / "custom_faces.json"
    registrar = CustomFaceRegistrar(
        library=build_library(tmp_path),
        cache_path=cache_path,
        client=client,
    )

    result = await registrar.register_all()

    assert result.registered_count == 2
    assert len(client.added) == 2
    assert cache_path.exists()


async def test_custom_face_registrar_skips_unchanged_cached_items(tmp_path: Path) -> None:
    client = FakeCustomFaceClient()
    cache_path = tmp_path / "custom_faces.json"
    registrar = CustomFaceRegistrar(
        library=build_library(tmp_path),
        cache_path=cache_path,
        client=client,
    )

    await registrar.register_all()
    client.added.clear()
    second = await registrar.register_all()

    assert second.skipped_count == 2
    assert client.added == []
```

Add to `tests/test_config.py`:

```python
def test_load_settings_parses_custom_face_registration_settings() -> None:
    env = base_env()
    env["MEDIA_REGISTER_CUSTOM_FACES"] = "true"
    env["MEDIA_CUSTOM_FACE_CACHE"] = "data/custom_faces.json"

    settings = load_settings(env)

    assert settings.media_register_custom_faces is True
    assert settings.media_custom_face_cache == Path("data/custom_faces.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_custom_faces.py tests/test_config.py::test_load_settings_parses_custom_face_registration_settings -q
```

Expected: fail because `qq_rolebot.custom_faces` and the new settings do not exist.

- [ ] **Step 3: Implement registration service and settings**

Create `qq_rolebot/custom_faces.py` with:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from qq_rolebot.stickers import StickerLibrary


class CustomFaceClient(Protocol):
    async def add_custom_face(self, *, file: str, is_origin: bool = True) -> Any:
        ...

    async def fetch_custom_face_detail(self, *, count: int = 48) -> Any:
        ...


@dataclass(frozen=True)
class CustomFaceRegistrationResult:
    registered_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class CustomFaceRegistrar:
    def __init__(
        self,
        *,
        library: StickerLibrary,
        cache_path: Path,
        client: CustomFaceClient,
    ) -> None:
        self.library = library
        self.cache_path = cache_path
        self.client = client

    async def register_all(self) -> CustomFaceRegistrationResult:
        cache = self._load_cache()
        registered = 0
        skipped = 0
        failed = 0
        for item in self.library.items():
            if not item.path.is_file():
                continue
            digest = self._sha256(item.path)
            cached = cache.get(item.id)
            if isinstance(cached, dict) and cached.get("sha256") == digest:
                skipped += 1
                continue
            try:
                await self.client.add_custom_face(file=str(item.path), is_origin=True)
                details = await self.client.fetch_custom_face_detail(count=48)
                registered += 1
                cache[item.id] = {
                    "sha256": digest,
                    "path": str(item.path),
                    "status": "registered",
                    "detail_count": len(details) if isinstance(details, list) else None,
                }
            except Exception as exc:
                failed += 1
                cache[item.id] = {
                    "sha256": digest,
                    "path": str(item.path),
                    "status": "failed",
                    "error": exc.__class__.__name__,
                }
        self._save_cache(cache)
        return CustomFaceRegistrationResult(
            registered_count=registered,
            skipped_count=skipped,
            failed_count=failed,
        )

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, ensure_ascii=True, indent=2), encoding="utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
```

Add `items()` to `StickerLibrary`:

```python
    def items(self) -> list[StickerItem]:
        return list(self._load_items())
```

Add settings:

```python
    media_register_custom_faces: bool
    media_custom_face_cache: Path
```

Parse:

```python
        media_register_custom_faces=_bool(env, "MEDIA_REGISTER_CUSTOM_FACES", True),
        media_custom_face_cache=Path(
            env.get("MEDIA_CUSTOM_FACE_CACHE", "data/custom_faces.json").strip()
            or "data/custom_faces.json"
        ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/custom_faces.py qq_rolebot/config.py qq_rolebot/stickers.py tests/test_custom_faces.py tests/test_config.py
git commit -m "feat: register active images as custom faces"
```

---

### Task 6: Wire Registration Into The Plugin

**Files:**
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing plugin registration test**

Add to `tests/test_plugin_smoke.py`:

```python
async def test_register_custom_faces_uses_bot_api(monkeypatch, tmp_path) -> None:
    set_env(monkeypatch)
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))
    root = tmp_path / "stickers"
    root.mkdir()
    image = root / "a.jpg"
    image.write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: a
    file: a.jpg
    type: custom_face
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )
    module.sticker_library = module.StickerLibrary(root=root, manifest_path=manifest)
    from dataclasses import replace

    module.settings = replace(
        module.settings,
        media_register_custom_faces=True,
        media_custom_face_cache=tmp_path / "cache.json",
    )
    calls = []

    class FakeBot:
        async def call_api(self, name, **params):
            calls.append((name, params))
            if name == "fetch_custom_face_detail":
                return []
            return {"result": 0}

    await module.register_custom_faces(FakeBot())

    assert calls[0][0] == "add_custom_face"
    assert calls[0][1]["file"] == str(image)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest tests/test_plugin_smoke.py::test_register_custom_faces_uses_bot_api -q
```

Expected: fail because `register_custom_faces` does not exist.

- [ ] **Step 3: Implement plugin registration hook**

In `qq_rolebot/plugins/roleplay_chat.py`, import `CustomFaceRegistrar` and define:

```python
class BotCustomFaceClient:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def add_custom_face(self, *, file: str, is_origin: bool = True):
        return await self.bot.call_api("add_custom_face", file=file, is_origin=is_origin)

    async def fetch_custom_face_detail(self, *, count: int = 48):
        return await self.bot.call_api("fetch_custom_face_detail", count=count)


async def register_custom_faces(bot: Bot) -> None:
    if not settings.media_register_custom_faces:
        return
    registrar = CustomFaceRegistrar(
        library=sticker_library,
        cache_path=settings.media_custom_face_cache,
        client=BotCustomFaceClient(bot),
    )
    await registrar.register_all()
```

Register it when the OneBot connection is available:

```python
if driver is not None:
    driver.on_startup(init_storage)
    driver.on_bot_connect(register_custom_faces)
```

If the installed NoneBot driver does not expose `on_bot_connect`, keep `on_startup(init_storage)` and call `register_custom_faces(bot)` lazily at the start of `_handle_message_locked` guarded by an in-process boolean flag.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command from Step 2. Expected: test passes.

- [ ] **Step 5: Commit**

```bash
git add qq_rolebot/plugins/roleplay_chat.py tests/test_plugin_smoke.py
git commit -m "feat: wire custom face registration"
```

---

### Task 7: Update Docs And Verify

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Test: full verification commands

- [ ] **Step 1: Update docs**

Add to `.env.example`:

```dotenv
MEDIA_REGISTER_CUSTOM_FACES=true
MEDIA_CUSTOM_FACE_CACHE=data/custom_faces.json
```

Add to README and deployment docs:

```markdown
- `MEDIA_REGISTER_CUSTOM_FACES`: when true, the bot calls NapCat `/add_custom_face` for active
  image assets and writes a local registration cache.
- `MEDIA_CUSTOM_FACE_CACHE`: server-local JSON cache for registration hashes; keep it under
  `data/` and out of git.
```

State that locally registered custom faces may still be sent as ordinary images because NapCat
`mface` is marketplace-sticker-specific.

- [ ] **Step 2: Run full verification**

Run:

```bash
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m ruff check .
/home/duscwalk/miniconda3/envs/qq-rolebot-wsl/bin/python -m pytest -q
git diff --check
git status --short --untracked-files=all
```

Expected: ruff passes, pytest passes, diff check has no output, and status shows only intentional files before the final commit.

- [ ] **Step 3: Commit docs**

```bash
git add .env.example README.md docs/deployment.md
git commit -m "docs: document custom face registration"
```

---

### Task 8: Deploy And Server Smoke Test

**Files:**
- No repository files changed.

- [ ] **Step 1: Deploy current branch to server**

Use the existing archive deploy flow with `scripts/deploy_server.sh` and SSH key
`/home/duscwalk/.ssh/id_ed25519`. Do not print secrets, tokens, QR URLs, or private SSH material.

- [ ] **Step 2: Verify server registration and repeat support**

On `120.26.110.68`, verify:

```bash
systemctl is-active qq-rolebot.service
systemctl is-active napcat.service
ss -ltnp | grep '127.0.0.1:8080'
test -f /opt/qq-rolebot/data/custom_faces.json
```

Use NapCat HTTP with token read only into a shell variable to call:

```bash
/fetch_custom_face_detail
/can_send_image
```

Expected: bot remains active, `can_send_image` returns true, and the custom face detail list includes the previously registered test image. Do not print token or QR URLs.

- [ ] **Step 3: Optional live test**

If the user triggers a `+1` on a marketplace sticker in a group, confirm logs show the bot sends an `mface` segment. If no marketplace sticker is available, note that local active images are registered as custom faces but still use image fallback for sending.

---

## Self-Review

- Spec coverage: active image registration, mface rendering, +1 original format, fallback behavior, docs, deployment, and server smoke test are covered.
- Plan text scan: no deferred implementation markers are present.
- Type consistency: `OutgoingMessage` and `RepeatMedia` use `emoji_id`, `emoji_package_id`, `key`, and `summary` consistently; `StickerItem.media_type` gates `is_sendable_mface`.
