# NapCatQQ Roleplay Group Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python QQ group roleplay bot that connects to a NapCatQQ QQ alternate account through OneBot 11 reverse WebSocket and replies as a restrained persona.

**Architecture:** NapCatQQ owns QQ login and OneBot transport. A NoneBot2 service receives group messages, routes admin commands, applies whitelist/trigger/rate policies, builds persona prompts, calls an OpenAI-compatible chat API, filters the response, and sends a group reply through OneBot.

**Tech Stack:** Python 3.11+, NoneBot2, nonebot-adapter-onebot, aiosqlite, httpx, PyYAML, pytest, pytest-asyncio.

---

## References

- NoneBot OneBot adapter connection guide: `https://onebot.adapters.nonebot.dev/docs/guide/setup/`
- NapCatQQ Linux installation guide: `https://napneko.github.io/guide/boot/Shell`
- NapCat API docs: `https://napcat.apifox.cn/`

Use OneBot V11 reverse WebSocket for version 1. Configure NapCat's reverse WebSocket target as one of the NoneBot endpoints documented by the adapter, preferably `ws://127.0.0.1:8080/onebot/v11/ws`.

## File Structure

- Create: `pyproject.toml` - project metadata, runtime dependencies, test tooling.
- Create: `.env.example` - safe example environment variables.
- Create: `README.md` - local development and server run commands.
- Create: `bot.py` - NoneBot application entrypoint.
- Create: `qq_rolebot/__init__.py` - package marker.
- Create: `qq_rolebot/config.py` - environment parsing and validated settings.
- Create: `qq_rolebot/storage.py` - SQLite schema and persistence methods.
- Create: `qq_rolebot/policy.py` - trigger decisions and in-memory rate limiter.
- Create: `qq_rolebot/persona.py` - persona YAML loading.
- Create: `qq_rolebot/prompting.py` - chat prompt construction.
- Create: `qq_rolebot/guardrails.py` - output cleanup and response suppression.
- Create: `qq_rolebot/model_client.py` - OpenAI-compatible chat client.
- Create: `qq_rolebot/admin.py` - admin command parsing and execution.
- Create: `qq_rolebot/service.py` - orchestration for one incoming group message.
- Create: `qq_rolebot/plugins/__init__.py` - plugin package marker.
- Create: `qq_rolebot/plugins/roleplay_chat.py` - NoneBot event adapter plugin.
- Create: `personas/default.yaml` - first persona configuration.
- Create: `tests/fixtures.py` - reusable test settings and fakes.
- Create: `tests/test_config.py` - configuration tests.
- Create: `tests/test_storage.py` - SQLite persistence tests.
- Create: `tests/test_policy.py` - trigger and rate-limit tests.
- Create: `tests/test_persona_prompt_guardrails.py` - persona, prompt, and filter tests.
- Create: `tests/test_model_client.py` - model client tests with `httpx.MockTransport`.
- Create: `tests/test_admin.py` - admin command tests.
- Create: `tests/test_service.py` - orchestration tests.
- Create: `docs/deployment.md` - Ubuntu, NapCatQQ, and systemd deployment notes.

## Version Control Note

The current workspace is not a git repository. Each task includes a checkpoint step. If the user initializes a repository before execution, use the listed `git add` and `git commit` commands. If the workspace remains non-git, run `git status` to confirm that no repository exists and continue without committing.

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `qq_rolebot/__init__.py`
- Create: `qq_rolebot/plugins/__init__.py`
- Create: `personas/default.yaml`

- [ ] **Step 1: Create dependency manifest**

Write `pyproject.toml`:

```toml
[project]
name = "qq-rolebot"
version = "0.1.0"
description = "NapCatQQ + NoneBot2 QQ group roleplay bot"
requires-python = ">=3.11"
dependencies = [
  "nonebot2[fastapi]>=2.4.0",
  "nonebot-adapter-onebot>=2.4.6",
  "aiosqlite>=0.20.0",
  "httpx>=0.27.0",
  "PyYAML>=6.0.2",
  "python-dotenv>=1.0.1",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2.0",
  "pytest-asyncio>=0.23.0",
  "ruff>=0.5.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Create safe environment example**

Write `.env.example`:

```bash
BOT_HOST=127.0.0.1
BOT_PORT=8080
ONEBOT_ACCESS_TOKEN=change-this-token
BOT_QQ=123456789
ADMIN_USERS=123456789
GROUP_WHITELIST=987654321
DATABASE_PATH=data/rolebot.sqlite3
PERSONA_PATH=personas/default.yaml
MODEL_API_BASE=https://api.openai.com/v1
MODEL_API_KEY=replace-with-api-key
MODEL_NAME=gpt-4.1-mini
MODEL_TIMEOUT_SECONDS=20
MAX_OUTPUT_CHARS=280
DEFAULT_RANDOM_REPLY_PROBABILITY=8
KEYWORDS=bot,hello
SENSITIVE_WORDS=
```

- [ ] **Step 3: Create package markers**

Write `qq_rolebot/__init__.py`:

```python
"""QQ roleplay bot package."""
```

Write `qq_rolebot/plugins/__init__.py`:

```python
"""NoneBot plugins for qq_rolebot."""
```

- [ ] **Step 4: Create default persona**

Write `personas/default.yaml`:

```yaml
name: "Mika"
style: "Casual, warm, concise, playful when the group is playful. Speak in Simplified Chinese unless the group uses another language."
relationship: "A familiar group member who chats naturally and avoids sounding like a customer support bot."
likes:
  - "light jokes"
  - "daily life"
  - "helping with small questions"
dislikes:
  - "long lectures"
  - "repeating the same point"
  - "pushing into conversations too often"
boundaries:
  - "Do not produce explicit sexual content."
  - "Do not harass or attack people."
  - "Do not request private credentials or personal secrets."
  - "Do not provide illegal instructions."
  - "Do not encourage spam, mass messaging, or platform abuse."
```

- [ ] **Step 5: Create README**

Write `README.md`:

````markdown
# QQ Rolebot

NapCatQQ + NoneBot2 roleplay bot for QQ group chat.

## Development

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
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
````

- [ ] **Step 6: Install dependencies**

Run:

```bash
python -m pip install -e ".[dev]"
```

Expected: package installation succeeds.

- [ ] **Step 7: Run empty test suite**

Run:

```bash
pytest
```

Expected: pytest runs and reports no collected tests or passes once later tests exist.

- [ ] **Step 8: Checkpoint**

If git is initialized, run:

```bash
git add pyproject.toml .env.example README.md qq_rolebot personas
git commit -m "chore: scaffold qq rolebot project"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 2: Configuration Loader

**Files:**
- Create: `tests/test_config.py`
- Create: `qq_rolebot/config.py`

- [ ] **Step 1: Write failing configuration tests**

Write `tests/test_config.py`:

```python
import pytest

from qq_rolebot.config import ConfigError, load_settings, parse_int_set, parse_str_list


def complete_env() -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10001,10002",
        "GROUP_WHITELIST": "20001",
        "DATABASE_PATH": "data/test.sqlite3",
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika,bot",
        "SENSITIVE_WORDS": "blocked",
    }


def test_parse_int_set_ignores_empty_values() -> None:
    assert parse_int_set("1, 2,,3") == {1, 2, 3}


def test_parse_str_list_trims_empty_values() -> None:
    assert parse_str_list(" hello, ,world ") == ["hello", "world"]


def test_load_settings_from_mapping() -> None:
    settings = load_settings(complete_env())

    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.bot_qq == 10001
    assert settings.admin_users == {10001, 10002}
    assert settings.group_whitelist == {20001}
    assert settings.keywords == ["mika", "bot"]
    assert settings.sensitive_words == ["blocked"]
    assert settings.default_random_reply_probability == 8


def test_load_settings_rejects_missing_required_value() -> None:
    env = complete_env()
    env["MODEL_API_KEY"] = ""

    with pytest.raises(ConfigError, match="MODEL_API_KEY"):
        load_settings(env)


def test_load_settings_rejects_invalid_probability() -> None:
    env = complete_env()
    env["DEFAULT_RANDOM_REPLY_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="DEFAULT_RANDOM_REPLY_PROBABILITY"):
        load_settings(env)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: FAIL because `qq_rolebot.config` does not exist.

- [ ] **Step 3: Implement configuration loader**

Write `qq_rolebot/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid."""


def parse_int_set(raw: str) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        item = part.strip()
        if item:
            values.add(int(item))
    return values


def parse_str_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    onebot_access_token: str
    bot_qq: int
    admin_users: set[int]
    group_whitelist: set[int]
    database_path: Path
    persona_path: Path
    model_api_base: str
    model_api_key: str
    model_name: str
    model_timeout_seconds: int
    max_output_chars: int
    default_random_reply_probability: int
    keywords: list[str]
    sensitive_words: list[str]


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        load_dotenv()
        env = os.environ

    probability = _int(env, "DEFAULT_RANDOM_REPLY_PROBABILITY", 8)
    if probability < 0 or probability > 100:
        raise ConfigError("DEFAULT_RANDOM_REPLY_PROBABILITY must be between 0 and 100")

    max_output_chars = _int(env, "MAX_OUTPUT_CHARS", 280)
    if max_output_chars < 1:
        raise ConfigError("MAX_OUTPUT_CHARS must be greater than 0")

    timeout = _int(env, "MODEL_TIMEOUT_SECONDS", 20)
    if timeout < 1:
        raise ConfigError("MODEL_TIMEOUT_SECONDS must be greater than 0")

    admin_users = parse_int_set(_required(env, "ADMIN_USERS"))
    group_whitelist = parse_int_set(_required(env, "GROUP_WHITELIST"))

    return Settings(
        host=env.get("BOT_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int(env, "BOT_PORT", 8080),
        onebot_access_token=_required(env, "ONEBOT_ACCESS_TOKEN"),
        bot_qq=int(_required(env, "BOT_QQ")),
        admin_users=admin_users,
        group_whitelist=group_whitelist,
        database_path=Path(env.get("DATABASE_PATH", "data/rolebot.sqlite3")),
        persona_path=Path(env.get("PERSONA_PATH", "personas/default.yaml")),
        model_api_base=_required(env, "MODEL_API_BASE").rstrip("/"),
        model_api_key=_required(env, "MODEL_API_KEY"),
        model_name=_required(env, "MODEL_NAME"),
        model_timeout_seconds=timeout,
        max_output_chars=max_output_chars,
        default_random_reply_probability=probability,
        keywords=parse_str_list(env.get("KEYWORDS", "")),
        sensitive_words=parse_str_list(env.get("SENSITIVE_WORDS", "")),
    )
```

- [ ] **Step 4: Run configuration tests**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_config.py qq_rolebot/config.py
git commit -m "feat: add runtime configuration loader"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 3: SQLite Storage

**Files:**
- Create: `tests/test_storage.py`
- Create: `qq_rolebot/storage.py`

- [ ] **Step 1: Write failing storage tests**

Write `tests/test_storage.py`:

```python
from pathlib import Path

import pytest

from qq_rolebot.storage import GroupSettings, MessageRecord, Storage


@pytest.mark.asyncio
async def test_group_settings_default_and_update(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.init()

    settings = await storage.get_group_settings(123)
    assert settings == GroupSettings(group_id=123, enabled=False, random_probability=8, muted_until=0)

    await storage.set_group_enabled(123, True)
    await storage.set_random_probability(123, 12)
    await storage.set_muted_until(123, 999)

    settings = await storage.get_group_settings(123)
    assert settings.enabled is True
    assert settings.random_probability == 12
    assert settings.muted_until == 999


@pytest.mark.asyncio
async def test_message_context_is_pruned(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3", context_limit=3)
    await storage.init()

    for index in range(5):
        await storage.save_message(
            MessageRecord(
                group_id=123,
                user_id=456,
                nickname=f"user-{index}",
                text=f"message-{index}",
                created_at=index,
            )
        )

    messages = await storage.recent_messages(123)
    assert [message.text for message in messages] == ["message-2", "message-3", "message-4"]


@pytest.mark.asyncio
async def test_clear_group_context(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.sqlite3")
    await storage.init()

    await storage.save_message(
        MessageRecord(group_id=123, user_id=456, nickname="amy", text="hello", created_at=1)
    )
    await storage.clear_context(123)

    assert await storage.recent_messages(123) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_storage.py -v
```

Expected: FAIL because `qq_rolebot.storage` does not exist.

- [ ] **Step 3: Implement SQLite storage**

Write `qq_rolebot/storage.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class GroupSettings:
    group_id: int
    enabled: bool
    random_probability: int
    muted_until: int


@dataclass(frozen=True)
class MessageRecord:
    group_id: int
    user_id: int
    nickname: str
    text: str
    created_at: int


class Storage:
    def __init__(self, path: Path, context_limit: int = 20, default_probability: int = 8) -> None:
        self.path = path
        self.context_limit = context_limit
        self.default_probability = default_probability

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    random_probability INTEGER NOT NULL,
                    muted_until INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS message_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_message_context_group_time
                ON message_context(group_id, created_at);

                CREATE TABLE IF NOT EXISTS user_notes (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                """
            )
            await db.commit()

    async def get_group_settings(self, group_id: int) -> GroupSettings:
        async with aiosqlite.connect(self.path) as db:
            row = await db.execute_fetchall(
                """
                SELECT group_id, enabled, random_probability, muted_until
                FROM group_settings
                WHERE group_id = ?
                """,
                (group_id,),
            )
            if not row:
                return GroupSettings(
                    group_id=group_id,
                    enabled=False,
                    random_probability=self.default_probability,
                    muted_until=0,
                )
            item = row[0]
            return GroupSettings(
                group_id=int(item[0]),
                enabled=bool(item[1]),
                random_probability=int(item[2]),
                muted_until=int(item[3]),
            )

    async def _ensure_group(self, db: aiosqlite.Connection, group_id: int) -> None:
        await db.execute(
            """
            INSERT OR IGNORE INTO group_settings
                (group_id, enabled, random_probability, muted_until)
            VALUES (?, 0, ?, 0)
            """,
            (group_id, self.default_probability),
        )

    async def set_group_enabled(self, group_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET enabled = ? WHERE group_id = ?",
                (1 if enabled else 0, group_id),
            )
            await db.commit()

    async def set_random_probability(self, group_id: int, probability: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET random_probability = ? WHERE group_id = ?",
                (probability, group_id),
            )
            await db.commit()

    async def set_muted_until(self, group_id: int, muted_until: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET muted_until = ? WHERE group_id = ?",
                (muted_until, group_id),
            )
            await db.commit()

    async def save_message(self, record: MessageRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO message_context (group_id, user_id, nickname, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record.group_id, record.user_id, record.nickname, record.text, record.created_at),
            )
            await db.execute(
                """
                DELETE FROM message_context
                WHERE group_id = ?
                  AND id NOT IN (
                    SELECT id FROM message_context
                    WHERE group_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                  )
                """,
                (record.group_id, record.group_id, self.context_limit),
            )
            await db.commit()

    async def recent_messages(self, group_id: int) -> list[MessageRecord]:
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall(
                """
                SELECT group_id, user_id, nickname, text, created_at
                FROM message_context
                WHERE group_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (group_id,),
            )
            return [
                MessageRecord(
                    group_id=int(row[0]),
                    user_id=int(row[1]),
                    nickname=str(row[2]),
                    text=str(row[3]),
                    created_at=int(row[4]),
                )
                for row in rows
            ]

    async def clear_context(self, group_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM message_context WHERE group_id = ?", (group_id,))
            await db.commit()
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
pytest tests/test_storage.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_storage.py qq_rolebot/storage.py
git commit -m "feat: add sqlite storage"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 4: Trigger Policy and Rate Limiting

**Files:**
- Create: `tests/test_policy.py`
- Create: `qq_rolebot/policy.py`

- [ ] **Step 1: Write failing policy tests**

Write `tests/test_policy.py`:

```python
from qq_rolebot.policy import IncomingMessage, RateLimiter, TriggerKind, decide_trigger


def message(text: str, *, at_bot: bool = False, user_id: int = 10) -> IncomingMessage:
    return IncomingMessage(
        group_id=20,
        user_id=user_id,
        nickname="tester",
        text=text,
        is_at_bot=at_bot,
        created_at=100,
    )


def test_direct_mention_triggers_reply() -> None:
    decision = decide_trigger(
        message("hello", at_bot=True),
        group_enabled=True,
        muted_until=0,
        keywords=[],
        random_probability=0,
        now=100,
        random_value=99,
    )

    assert decision.should_reply is True
    assert decision.kind == TriggerKind.MENTION


def test_disabled_group_does_not_reply() -> None:
    decision = decide_trigger(
        message("hello", at_bot=True),
        group_enabled=False,
        muted_until=0,
        keywords=[],
        random_probability=100,
        now=100,
        random_value=0,
    )

    assert decision.should_reply is False
    assert decision.reason == "group disabled"


def test_keyword_triggers_reply() -> None:
    decision = decide_trigger(
        message("mika are you here"),
        group_enabled=True,
        muted_until=0,
        keywords=["mika"],
        random_probability=0,
        now=100,
        random_value=99,
    )

    assert decision.should_reply is True
    assert decision.kind == TriggerKind.KEYWORD


def test_random_probability_uses_percent() -> None:
    decision = decide_trigger(
        message("ordinary chat"),
        group_enabled=True,
        muted_until=0,
        keywords=[],
        random_probability=8,
        now=100,
        random_value=7,
    )

    assert decision.should_reply is True
    assert decision.kind == TriggerKind.RANDOM


def test_rate_limiter_blocks_group_burst() -> None:
    limiter = RateLimiter(group_limit=3, group_window_seconds=60, user_cooldown_seconds=10)

    assert limiter.allow(1, 10, now=1) is True
    limiter.record(1, 10, now=1)
    assert limiter.allow(1, 11, now=2) is True
    limiter.record(1, 11, now=2)
    assert limiter.allow(1, 12, now=3) is True
    limiter.record(1, 12, now=3)

    assert limiter.allow(1, 13, now=4) is False
    assert limiter.allow(1, 13, now=62) is True


def test_rate_limiter_blocks_same_user_cooldown() -> None:
    limiter = RateLimiter(group_limit=3, group_window_seconds=60, user_cooldown_seconds=10)

    limiter.record(1, 10, now=100)

    assert limiter.allow(1, 10, now=105) is False
    assert limiter.allow(1, 10, now=111) is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_policy.py -v
```

Expected: FAIL because `qq_rolebot.policy` does not exist.

- [ ] **Step 3: Implement policy module**

Write `qq_rolebot/policy.py`:

```python
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum


class TriggerKind(StrEnum):
    NONE = "none"
    MENTION = "mention"
    KEYWORD = "keyword"
    RANDOM = "random"


@dataclass(frozen=True)
class IncomingMessage:
    group_id: int
    user_id: int
    nickname: str
    text: str
    is_at_bot: bool
    created_at: int


@dataclass(frozen=True)
class TriggerDecision:
    should_reply: bool
    kind: TriggerKind
    reason: str


def decide_trigger(
    message: IncomingMessage,
    *,
    group_enabled: bool,
    muted_until: int,
    keywords: list[str],
    random_probability: int,
    now: int,
    random_value: int,
) -> TriggerDecision:
    if not group_enabled:
        return TriggerDecision(False, TriggerKind.NONE, "group disabled")
    if muted_until > now:
        return TriggerDecision(False, TriggerKind.NONE, "group muted")
    if message.is_at_bot:
        return TriggerDecision(True, TriggerKind.MENTION, "mentioned")

    lowered = message.text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            return TriggerDecision(True, TriggerKind.KEYWORD, "keyword")

    if random_probability > 0 and random_value < random_probability:
        return TriggerDecision(True, TriggerKind.RANDOM, "random")

    return TriggerDecision(False, TriggerKind.NONE, "no trigger")


class RateLimiter:
    def __init__(
        self,
        *,
        group_limit: int = 3,
        group_window_seconds: int = 60,
        user_cooldown_seconds: int = 10,
    ) -> None:
        self.group_limit = group_limit
        self.group_window_seconds = group_window_seconds
        self.user_cooldown_seconds = user_cooldown_seconds
        self._group_events: dict[int, deque[int]] = defaultdict(deque)
        self._user_events: dict[tuple[int, int], int] = {}

    def allow(self, group_id: int, user_id: int, *, now: int) -> bool:
        self._prune(group_id, now)
        user_key = (group_id, user_id)
        last_user_reply = self._user_events.get(user_key)
        if last_user_reply is not None and now - last_user_reply < self.user_cooldown_seconds:
            return False
        return len(self._group_events[group_id]) < self.group_limit

    def record(self, group_id: int, user_id: int, *, now: int) -> None:
        self._prune(group_id, now)
        self._group_events[group_id].append(now)
        self._user_events[(group_id, user_id)] = now

    def _prune(self, group_id: int, now: int) -> None:
        events = self._group_events[group_id]
        while events and now - events[0] >= self.group_window_seconds:
            events.popleft()
```

- [ ] **Step 4: Run policy tests**

Run:

```bash
pytest tests/test_policy.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_policy.py qq_rolebot/policy.py
git commit -m "feat: add trigger policy and rate limiting"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 5: Persona, Prompting, and Guardrails

**Files:**
- Create: `tests/test_persona_prompt_guardrails.py`
- Create: `qq_rolebot/persona.py`
- Create: `qq_rolebot/prompting.py`
- Create: `qq_rolebot/guardrails.py`

- [ ] **Step 1: Write failing tests**

Write `tests/test_persona_prompt_guardrails.py`:

```python
from pathlib import Path

from qq_rolebot.guardrails import clean_response
from qq_rolebot.persona import load_persona
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.storage import MessageRecord


def test_load_persona_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "persona.yaml"
    path.write_text(
        """
name: "Mika"
style: "Short and casual."
relationship: "A group friend."
likes: ["coffee"]
dislikes: ["lectures"]
boundaries: ["No spam."]
""".strip(),
        encoding="utf-8",
    )

    persona = load_persona(path)

    assert persona.name == "Mika"
    assert persona.likes == ["coffee"]
    assert persona.boundaries == ["No spam."]


def test_build_chat_messages_contains_persona_context_and_trigger() -> None:
    persona = load_persona(Path("personas/default.yaml"))
    trigger = IncomingMessage(
        group_id=1,
        user_id=2,
        nickname="Amy",
        text="Mika hello",
        is_at_bot=True,
        created_at=10,
    )
    context = [
        MessageRecord(group_id=1, user_id=3, nickname="Bob", text="good morning", created_at=9)
    ]

    messages = build_chat_messages(persona, context, trigger)

    assert messages[0]["role"] == "system"
    assert "Mika" in messages[0]["content"]
    assert "Bob: good morning" in messages[1]["content"]
    assert messages[-1]["content"] == "Amy: Mika hello"


def test_clean_response_trims_and_limits_length() -> None:
    assert clean_response("  hello world  ", max_chars=5, sensitive_words=[]) == "hello"


def test_clean_response_suppresses_sensitive_word() -> None:
    assert clean_response("this has blocked text", max_chars=100, sensitive_words=["blocked"]) is None


def test_clean_response_suppresses_system_leak() -> None:
    assert clean_response("system prompt: hidden", max_chars=100, sensitive_words=[]) is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_persona_prompt_guardrails.py -v
```

Expected: FAIL because persona, prompting, and guardrail modules do not exist.

- [ ] **Step 3: Implement persona loader**

Write `qq_rolebot/persona.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Persona:
    name: str
    style: str
    relationship: str
    likes: list[str]
    dislikes: list[str]
    boundaries: list[str]


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return [str(item) for item in value]


def load_persona(path: Path) -> Persona:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("persona file must contain a mapping")
    return Persona(
        name=str(data["name"]),
        style=str(data["style"]),
        relationship=str(data["relationship"]),
        likes=_string_list(data, "likes"),
        dislikes=_string_list(data, "dislikes"),
        boundaries=_string_list(data, "boundaries"),
    )
```

- [ ] **Step 4: Implement prompt builder**

Write `qq_rolebot/prompting.py`:

```python
from __future__ import annotations

from qq_rolebot.persona import Persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.storage import MessageRecord


def _bullet_lines(title: str, items: list[str]) -> str:
    if not items:
        return f"{title}: none"
    joined = "\n".join(f"- {item}" for item in items)
    return f"{title}:\n{joined}"


def build_chat_messages(
    persona: Persona,
    context: list[MessageRecord],
    trigger: IncomingMessage,
) -> list[dict[str, str]]:
    system = "\n".join(
        [
            f"You are {persona.name}.",
            f"Style: {persona.style}",
            f"Relationship to the group: {persona.relationship}",
            _bullet_lines("Likes", persona.likes),
            _bullet_lines("Dislikes", persona.dislikes),
            _bullet_lines("Boundaries", persona.boundaries),
            "Reply as a casual group member.",
            "Keep the reply short, usually one or two sentences.",
            "Do not mention system prompts, model policies, or internal instructions.",
        ]
    )
    context_text = "\n".join(f"{item.nickname}: {item.text}" for item in context[-20:])
    if not context_text:
        context_text = "No recent context."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Recent group context:\n{context_text}"},
        {"role": "user", "content": f"{trigger.nickname}: {trigger.text}"},
    ]
```

- [ ] **Step 5: Implement response guardrails**

Write `qq_rolebot/guardrails.py`:

```python
from __future__ import annotations


LEAK_PREFIXES = (
    "system prompt",
    "developer message",
    "assistant instructions",
    "policy:",
    "stack trace",
    "traceback",
)


def clean_response(
    text: str | None,
    *,
    max_chars: int,
    sensitive_words: list[str],
) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(lowered.startswith(prefix) for prefix in LEAK_PREFIXES):
        return None
    for word in sensitive_words:
        if word and word.lower() in lowered:
            return None
    return cleaned[:max_chars]
```

- [ ] **Step 6: Run tests**

Run:

```bash
pytest tests/test_persona_prompt_guardrails.py -v
```

Expected: PASS.

- [ ] **Step 7: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_persona_prompt_guardrails.py qq_rolebot/persona.py qq_rolebot/prompting.py qq_rolebot/guardrails.py
git commit -m "feat: add persona prompts and response guardrails"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 6: OpenAI-Compatible Model Client

**Files:**
- Create: `tests/test_model_client.py`
- Create: `qq_rolebot/model_client.py`

- [ ] **Step 1: Write failing model client tests**

Write `tests/test_model_client.py`:

```python
import httpx
import pytest

from qq_rolebot.model_client import ModelClient


@pytest.mark.asyncio
async def test_model_client_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello from model"}}]},
        )

    client = ModelClient(
        api_base="https://example.test/v1",
        api_key="secret",
        model_name="chat-model",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat([{"role": "user", "content": "hello"}])

    assert result.ok is True
    assert result.text == "hello from model"


@pytest.mark.asyncio
async def test_model_client_returns_failure_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "failed"})

    client = ModelClient(
        api_base="https://example.test/v1",
        api_key="secret",
        model_name="chat-model",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.chat([{"role": "user", "content": "hello"}])

    assert result.ok is False
    assert "500" in result.error
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_model_client.py -v
```

Expected: FAIL because `qq_rolebot.model_client` does not exist.

- [ ] **Step 3: Implement model client**

Write `qq_rolebot/model_client.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ModelResult:
    ok: bool
    text: str | None = None
    error: str | None = None


class ModelClient:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model_name: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.8,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return ModelResult(ok=False, error=str(exc))

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return ModelResult(ok=False, error=f"invalid model response: {exc}")
        return ModelResult(ok=True, text=str(text))
```

- [ ] **Step 4: Run model client tests**

Run:

```bash
pytest tests/test_model_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_model_client.py qq_rolebot/model_client.py
git commit -m "feat: add chat model client"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 7: Admin Commands

**Files:**
- Create: `tests/test_admin.py`
- Create: `qq_rolebot/admin.py`

- [ ] **Step 1: Write failing admin tests**

Write `tests/test_admin.py`:

```python
from pathlib import Path

import pytest

from qq_rolebot.admin import handle_admin_command, is_admin_command, parse_duration_seconds
from qq_rolebot.config import load_settings
from qq_rolebot.storage import Storage


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika",
        "SENSITIVE_WORDS": "",
    }


def test_is_admin_command() -> None:
    assert is_admin_command("/bot on") is True
    assert is_admin_command(" /bot status ") is True
    assert is_admin_command("hello") is False


def test_parse_duration_seconds() -> None:
    assert parse_duration_seconds("10m") == 600
    assert parse_duration_seconds("2h") == 7200
    assert parse_duration_seconds("30s") == 30


@pytest.mark.asyncio
async def test_admin_on_off_status(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()

    assert await handle_admin_command(
        "/bot on", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    ) == "bot enabled"
    assert (await storage.get_group_settings(20)).enabled is True

    status = await handle_admin_command(
        "/bot status", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    )
    assert "enabled=True" in status

    assert await handle_admin_command(
        "/bot off", sender_id=10, group_id=20, now=100, settings=settings, storage=storage
    ) == "bot disabled"
    assert (await storage.get_group_settings(20)).enabled is False


@pytest.mark.asyncio
async def test_unauthorized_admin_command_is_silent(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()

    result = await handle_admin_command(
        "/bot on", sender_id=99, group_id=20, now=100, settings=settings, storage=storage
    )

    assert result is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_admin.py -v
```

Expected: FAIL because `qq_rolebot.admin` does not exist.

- [ ] **Step 3: Implement admin commands**

Write `qq_rolebot/admin.py`:

```python
from __future__ import annotations

from qq_rolebot.config import Settings
from qq_rolebot.storage import Storage


def is_admin_command(text: str) -> bool:
    return text.strip().startswith("/bot")


def parse_duration_seconds(raw: str) -> int:
    value = raw.strip().lower()
    if len(value) < 2:
        raise ValueError("duration must include a unit")
    amount = int(value[:-1])
    unit = value[-1]
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    raise ValueError("duration unit must be s, m, or h")


async def handle_admin_command(
    text: str,
    *,
    sender_id: int,
    group_id: int,
    now: int,
    settings: Settings,
    storage: Storage,
) -> str | None:
    if sender_id not in settings.admin_users:
        return None

    parts = text.strip().split()
    if len(parts) < 2 or parts[0] != "/bot":
        return "usage: /bot on|off|mute|prob|clear|status"

    command = parts[1].lower()
    if command == "on":
        await storage.set_group_enabled(group_id, True)
        return "bot enabled"
    if command == "off":
        await storage.set_group_enabled(group_id, False)
        return "bot disabled"
    if command == "mute":
        if len(parts) != 3:
            return "usage: /bot mute 10m"
        seconds = parse_duration_seconds(parts[2])
        await storage.set_muted_until(group_id, now + seconds)
        return f"bot muted for {parts[2]}"
    if command == "prob":
        if len(parts) != 3:
            return "usage: /bot prob 8"
        probability = int(parts[2])
        if probability < 0 or probability > 100:
            return "probability must be between 0 and 100"
        await storage.set_random_probability(group_id, probability)
        return f"random reply probability set to {probability}%"
    if command == "clear":
        await storage.clear_context(group_id)
        return "context cleared"
    if command == "status":
        group = await storage.get_group_settings(group_id)
        return (
            f"enabled={group.enabled}, "
            f"random_probability={group.random_probability}%, "
            f"muted_until={group.muted_until}"
        )
    return "usage: /bot on|off|mute|prob|clear|status"
```

- [ ] **Step 4: Run admin tests**

Run:

```bash
pytest tests/test_admin.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_admin.py qq_rolebot/admin.py
git commit -m "feat: add admin commands"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 8: Message Orchestration Service

**Files:**
- Create: `tests/test_service.py`
- Create: `qq_rolebot/service.py`

- [ ] **Step 1: Write failing service tests**

Write `tests/test_service.py`:

```python
from pathlib import Path

import pytest

from qq_rolebot.config import load_settings
from qq_rolebot.model_client import ModelResult
from qq_rolebot.policy import IncomingMessage, RateLimiter
from qq_rolebot.service import ChatService
from qq_rolebot.storage import Storage


class FakeModel:
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        assert messages
        return ModelResult(ok=True, text="model reply")


def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika",
        "SENSITIVE_WORDS": "",
    }


def msg(text: str, *, at_bot: bool, sender: int = 11, group: int = 20) -> IncomingMessage:
    return IncomingMessage(
        group_id=group,
        user_id=sender,
        nickname="Amy",
        text=text,
        is_at_bot=at_bot,
        created_at=100,
    )


@pytest.mark.asyncio
async def test_service_handles_admin_command(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("/bot on", at_bot=False, sender=10), random_value=99)

    assert reply == "bot enabled"
    assert (await storage.get_group_settings(20)).enabled is True


@pytest.mark.asyncio
async def test_service_replies_to_mention_when_enabled(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    await storage.set_group_enabled(20, True)
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("hello", at_bot=True), random_value=99)

    assert reply == "model reply"


@pytest.mark.asyncio
async def test_service_ignores_non_whitelisted_group(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=FakeModel(),
        rate_limiter=RateLimiter(),
    )

    reply = await service.handle(msg("hello", at_bot=True, group=999), random_value=99)

    assert reply is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/test_service.py -v
```

Expected: FAIL because `qq_rolebot.service` does not exist.

- [ ] **Step 3: Implement orchestration service**

Write `qq_rolebot/service.py`:

```python
from __future__ import annotations

from typing import Protocol

from qq_rolebot.admin import handle_admin_command, is_admin_command
from qq_rolebot.config import Settings
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import IncomingMessage, RateLimiter, decide_trigger
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.storage import MessageRecord, Storage


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        ...


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        model: ChatModel,
        rate_limiter: RateLimiter,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model = model
        self.rate_limiter = rate_limiter
        self.persona = load_persona(settings.persona_path)

    async def handle(self, message: IncomingMessage, *, random_value: int) -> str | None:
        if message.group_id not in self.settings.group_whitelist:
            return None

        await self.storage.save_message(
            MessageRecord(
                group_id=message.group_id,
                user_id=message.user_id,
                nickname=message.nickname,
                text=message.text,
                created_at=message.created_at,
            )
        )

        if is_admin_command(message.text):
            return await handle_admin_command(
                message.text,
                sender_id=message.user_id,
                group_id=message.group_id,
                now=message.created_at,
                settings=self.settings,
                storage=self.storage,
            )

        group = await self.storage.get_group_settings(message.group_id)
        decision = decide_trigger(
            message,
            group_enabled=group.enabled,
            muted_until=group.muted_until,
            keywords=self.settings.keywords,
            random_probability=group.random_probability,
            now=message.created_at,
            random_value=random_value,
        )
        if not decision.should_reply:
            return None

        if not self.rate_limiter.allow(message.group_id, message.user_id, now=message.created_at):
            return None

        context = await self.storage.recent_messages(message.group_id)
        result = await self.model.chat(build_chat_messages(self.persona, context, message))
        if not result.ok:
            return None

        reply = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            return None

        self.rate_limiter.record(message.group_id, message.user_id, now=message.created_at)
        return reply
```

- [ ] **Step 4: Run service tests**

Run:

```bash
pytest tests/test_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_service.py qq_rolebot/service.py
git commit -m "feat: add message orchestration service"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 9: NoneBot Entrypoint and OneBot Plugin

**Files:**
- Create: `tests/test_plugin_smoke.py`
- Create: `bot.py`
- Create: `qq_rolebot/plugins/roleplay_chat.py`

- [ ] **Step 1: Write failing smoke test**

Write `tests/test_plugin_smoke.py`:

```python
import importlib


def test_bot_entrypoint_imports() -> None:
    module = importlib.import_module("bot")
    assert hasattr(module, "main")


def test_roleplay_plugin_imports() -> None:
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    assert hasattr(module, "extract_message_text")
```

- [ ] **Step 2: Run smoke test to verify failure**

Run:

```bash
pytest tests/test_plugin_smoke.py -v
```

Expected: FAIL because `bot.py` and `qq_rolebot.plugins.roleplay_chat` do not exist.

- [ ] **Step 3: Implement NoneBot entrypoint**

Write `bot.py`:

```python
from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from qq_rolebot.config import load_settings


def main() -> None:
    settings = load_settings()
    nonebot.init(
        driver="~fastapi",
        host=settings.host,
        port=settings.port,
        onebot_access_token=settings.onebot_access_token,
    )
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    nonebot.load_plugin("qq_rolebot.plugins.roleplay_chat")
    nonebot.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Implement OneBot plugin adapter**

Write `qq_rolebot/plugins/roleplay_chat.py`:

```python
from __future__ import annotations

import random
import time

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageSegment

from qq_rolebot.config import load_settings
from qq_rolebot.model_client import ModelClient
from qq_rolebot.policy import IncomingMessage, RateLimiter
from qq_rolebot.service import ChatService
from qq_rolebot.storage import Storage


settings = load_settings()
storage = Storage(
    settings.database_path,
    context_limit=20,
    default_probability=settings.default_random_reply_probability,
)
model = ModelClient(
    api_base=settings.model_api_base,
    api_key=settings.model_api_key,
    model_name=settings.model_name,
    timeout_seconds=settings.model_timeout_seconds,
)
service = ChatService(
    settings=settings,
    storage=storage,
    model=model,
    rate_limiter=RateLimiter(),
)

matcher = on_message(priority=50, block=False)


@get_driver().on_startup
async def init_storage() -> None:
    await storage.init()


def extract_message_text(event: GroupMessageEvent) -> str:
    return event.get_plaintext().strip()


def is_at_bot(event: GroupMessageEvent, bot_id: int) -> bool:
    for segment in event.message:
        if segment.type == "at" and str(segment.data.get("qq")) == str(bot_id):
            return True
    return False


@matcher.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    text = extract_message_text(event)
    if not text:
        return

    sender = event.sender
    nickname = sender.card or sender.nickname or str(event.user_id)
    incoming = IncomingMessage(
        group_id=int(event.group_id),
        user_id=int(event.user_id),
        nickname=nickname,
        text=text,
        is_at_bot=is_at_bot(event, settings.bot_qq),
        created_at=int(getattr(event, "time", int(time.time()))),
    )
    reply = await service.handle(incoming, random_value=random.randrange(100))
    if reply:
        await bot.send(event, MessageSegment.text(reply))
```

- [ ] **Step 5: Run smoke test**

Run:

```bash
pytest tests/test_plugin_smoke.py -v
```

Expected: PASS when test environment provides required env vars, or FAIL with `ConfigError` if env vars are missing.

- [ ] **Step 6: Make smoke test independent from real secrets**

If Step 5 fails with `ConfigError`, modify `tests/test_plugin_smoke.py` to set safe environment values before import:

```python
import importlib


def set_env(monkeypatch) -> None:
    values = {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10",
        "GROUP_WHITELIST": "20",
        "DATABASE_PATH": "data/test.sqlite3",
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika",
        "SENSITIVE_WORDS": "",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_bot_entrypoint_imports(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("bot")
    assert hasattr(module, "main")


def test_roleplay_plugin_imports(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    assert hasattr(module, "extract_message_text")
```

- [ ] **Step 7: Run smoke test again**

Run:

```bash
pytest tests/test_plugin_smoke.py -v
```

Expected: PASS.

- [ ] **Step 8: Checkpoint**

If git is initialized, run:

```bash
git add tests/test_plugin_smoke.py bot.py qq_rolebot/plugins/roleplay_chat.py
git commit -m "feat: wire nonebot onebot plugin"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

### Task 10: Deployment Notes and Final Verification

**Files:**
- Create: `docs/deployment.md`

- [ ] **Step 1: Write deployment guide**

Write `docs/deployment.md`:

````markdown
# Deployment

Target server: Ubuntu.

## 1. Install project

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv git
cd /opt
sudo mkdir -p qq-rolebot
sudo chown "$USER:$USER" qq-rolebot
cd /opt/qq-rolebot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` and set:

- `ONEBOT_ACCESS_TOKEN`
- `BOT_QQ`
- `ADMIN_USERS`
- `GROUP_WHITELIST`
- `MODEL_API_BASE`
- `MODEL_API_KEY`
- `MODEL_NAME`

## 2. Run tests on the server

```bash
source /opt/qq-rolebot/.venv/bin/activate
cd /opt/qq-rolebot
pytest
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
ExecStart=/opt/qq-rolebot/.venv/bin/python /opt/qq-rolebot/bot.py
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

## 5. First group test

In the whitelisted QQ group:

```text
/bot on
```

Then mention the QQ alternate account. The bot should reply once, stay within rate limits, and ignore non-whitelisted groups.
````

- [ ] **Step 2: Run full tests**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 3: Run lint**

Run:

```bash
ruff check .
```

Expected: PASS.

- [ ] **Step 4: Final import verification**

Run:

```bash
python -c "import bot; import qq_rolebot; print('ok')"
```

Expected with env vars set: `ok`.

- [ ] **Step 5: Checkpoint**

If git is initialized, run:

```bash
git add docs/deployment.md
git commit -m "docs: add qq rolebot deployment guide"
```

If git is not initialized, run:

```bash
git status
```

Expected without git: `fatal: not a git repository`.

---

## Self-Review

- Spec coverage: The plan covers NapCatQQ plus OneBot V11 reverse WebSocket, NoneBot2 runtime, environment config, SQLite memory, group whitelist, admin list, mention/keyword/random triggers, rate limits, persona prompts, model calls, output filtering, tests, and Ubuntu deployment notes.
- Scope: The plan stays within the approved first version. It excludes dashboards, vector memory, mass messaging, automatic group joining, and behavior that tries to bypass platform restrictions.
- Type consistency: `IncomingMessage`, `GroupSettings`, `MessageRecord`, `Settings`, `ModelResult`, `Storage`, `RateLimiter`, and `ChatService` are introduced before later tasks depend on them.
- Execution note: Task 9 imports the plugin, which loads runtime config at module import time. The smoke test includes a concrete monkeypatch path so tests do not require real secrets.
