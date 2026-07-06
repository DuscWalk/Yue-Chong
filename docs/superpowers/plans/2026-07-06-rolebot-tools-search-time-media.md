# Rolebot Tools, Search, Time, And Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic tool layer for current time, Tavily web search, PRTS persona-source lookup, and QQ message segment summaries without disrupting the existing roleplay chat flow.

**Architecture:** Keep tool routing outside the model. The service asks a `ToolRunner` for either a direct reply or compact context, then builds the final model prompt. The NoneBot plugin remains the transport boundary: it extracts richer message text/reply metadata and renders text replies.

**Tech Stack:** Python 3.11, NoneBot2, OneBot V11, httpx, PyYAML, aiosqlite, pytest, pytest-asyncio, ruff.

---

## Scope

This plan implements the first text-focused slice from the approved spec:

- Config for tool features and Tavily.
- Persona `Sources` support and PRTS Chongyue source in `personas/default.yaml`.
- Addressing and intent routing.
- Current time direct replies.
- Tavily client and compact search context.
- Persona source client with URL allowlist and simple HTML-to-text extraction.
- Prompt injection for tool context.
- Service integration with rate limits preserved.
- Message segment summaries for image, record, face, file, and unknown segments.
- Deployment of code and `TAVILY_API_KEY` through server environment only.

Voice synthesis, ASR, file transfer workflows, and non-text outgoing replies are excluded from this first implementation. The code boundaries added here should make those future additions straightforward.

## File Structure

- Modify `qq_rolebot/config.py`
  - Add optional tool/search config fields.
  - Keep required chat/model config unchanged.

- Modify `qq_rolebot/policy.py`
  - Add `is_reply_to_bot: bool = False` to `IncomingMessage`.

- Modify `qq_rolebot/persona.py`
  - Add `PersonaSource`.
  - Parse `Sources` from long roleplay YAML.

- Modify `personas/default.yaml`
  - Add `Sources` with PRTS Chongyue URL.

- Create `qq_rolebot/message_segments.py`
  - Convert OneBot message segments into text summaries and detect reply segments.

- Create `qq_rolebot/tool_router.py`
  - Deterministic address gate, intent detection, and search cooldown.

- Create `qq_rolebot/time_tool.py`
  - Format current time/date direct replies.

- Create `qq_rolebot/tavily.py`
  - Tavily API client and search result formatting.

- Create `qq_rolebot/persona_sources.py`
  - Fetch only allowlisted persona URLs and extract compact text.

- Create `qq_rolebot/tool_runner.py`
  - Compose router, time tool, Tavily client, and persona source client.

- Modify `qq_rolebot/prompting.py`
  - Accept optional tool context and include it in the system/user prompt.

- Modify `qq_rolebot/service.py`
  - Invoke the tool runner before model calls.

- Modify `qq_rolebot/plugins/roleplay_chat.py`
  - Build richer incoming messages and instantiate the tool runner.

- Modify `.env.example`, `README.md`, and `docs/deployment.md`
  - Document new environment variables without real secrets.

- Add tests:
  - `tests/test_tool_router.py`
  - `tests/test_time_tool.py`
  - `tests/test_tavily.py`
  - `tests/test_persona_sources.py`
  - `tests/test_message_segments.py`
  - Update existing config/persona/prompt/service/plugin tests.

## Workspace Note

The current workspace is not a git repository. Each task includes a checkpoint step. If the user initializes git before execution, run the listed `git add` and `git commit` commands. If the workspace remains non-git, run `git status` to confirm that no repository exists and continue without committing.

---

### Task 1: Tool Configuration And Persona Sources

**Files:**
- Modify: `qq_rolebot/config.py`
- Modify: `qq_rolebot/persona.py`
- Modify: `personas/default.yaml`
- Test: `tests/test_config.py`
- Test: `tests/test_persona_prompt_guardrails.py`

- [ ] **Step 1: Write failing config tests**

Append this test to `tests/test_config.py`:

```python
def test_load_settings_reads_tool_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.tavily_api_key == ""
    assert settings.tavily_api_base == "https://api.tavily.com"
    assert settings.search_max_results == 5
    assert settings.search_timeout_seconds == 10
    assert settings.search_cooldown_seconds == 20
    assert settings.tools_enable_search is True
    assert settings.tools_enable_persona_sources is True
    assert settings.tools_enable_time is True


def test_load_settings_reads_tool_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "TAVILY_API_KEY": "test-key",
            "TAVILY_API_BASE": "https://search.example.test",
            "SEARCH_MAX_RESULTS": "3",
            "SEARCH_TIMEOUT_SECONDS": "4",
            "SEARCH_COOLDOWN_SECONDS": "7",
            "TOOLS_ENABLE_SEARCH": "false",
            "TOOLS_ENABLE_PERSONA_SOURCES": "0",
            "TOOLS_ENABLE_TIME": "no",
        }
    )

    settings = load_settings(env)

    assert settings.tavily_api_key == "test-key"
    assert settings.tavily_api_base == "https://search.example.test"
    assert settings.search_max_results == 3
    assert settings.search_timeout_seconds == 4
    assert settings.search_cooldown_seconds == 7
    assert settings.tools_enable_search is False
    assert settings.tools_enable_persona_sources is False
    assert settings.tools_enable_time is False
```

- [ ] **Step 2: Write failing persona source tests**

Add to `tests/test_persona_prompt_guardrails.py`:

```python
def test_load_persona_sources_from_roleplay_yaml(tmp_path: Path) -> None:
    path = tmp_path / "persona.yaml"
    path.write_text(
        """
user_name: Doctor
assistant_name: Chongyue
language: zh-CN
Profile: |
  - Visitor.
Skills: |
  - Calm.
Background: |
  - Talks through QQ.
Rules: |
  - Plain text only.
Sources:
  - name: PRTS Chongyue
    url: https://prts.wiki/w/%E9%87%8D%E5%B2%B3
    purpose: character profile
""".strip(),
        encoding="utf-8",
    )

    persona = load_persona(path)

    assert len(persona.sources) == 1
    assert persona.sources[0].name == "PRTS Chongyue"
    assert persona.sources[0].url == "https://prts.wiki/w/%E9%87%8D%E5%B2%B3"
    assert persona.sources[0].purpose == "character profile"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_config.py tests/test_persona_prompt_guardrails.py -q
```

Expected: FAIL because `Settings` has no tool fields and `Persona` has no `sources`.

- [ ] **Step 4: Implement config fields**

In `qq_rolebot/config.py`, add this helper after `_int`:

```python
def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be a boolean")
```

Extend `Settings`:

```python
    tavily_api_key: str
    tavily_api_base: str
    search_max_results: int
    search_timeout_seconds: int
    search_cooldown_seconds: int
    tools_enable_search: bool
    tools_enable_persona_sources: bool
    tools_enable_time: bool
```

Add validation before the `return Settings(...)` block:

```python
    search_max_results = _int(env, "SEARCH_MAX_RESULTS", 5)
    if search_max_results < 1:
        raise ConfigError("SEARCH_MAX_RESULTS must be greater than 0")

    search_timeout_seconds = _int(env, "SEARCH_TIMEOUT_SECONDS", 10)
    if search_timeout_seconds < 1:
        raise ConfigError("SEARCH_TIMEOUT_SECONDS must be greater than 0")

    search_cooldown_seconds = _int(env, "SEARCH_COOLDOWN_SECONDS", 20)
    if search_cooldown_seconds < 0:
        raise ConfigError("SEARCH_COOLDOWN_SECONDS must be greater than or equal to 0")
```

Add these fields in the `Settings(...)` call:

```python
        tavily_api_key=env.get("TAVILY_API_KEY", "").strip(),
        tavily_api_base=env.get("TAVILY_API_BASE", "https://api.tavily.com").strip().rstrip("/")
        or "https://api.tavily.com",
        search_max_results=search_max_results,
        search_timeout_seconds=search_timeout_seconds,
        search_cooldown_seconds=search_cooldown_seconds,
        tools_enable_search=_bool(env, "TOOLS_ENABLE_SEARCH", True),
        tools_enable_persona_sources=_bool(env, "TOOLS_ENABLE_PERSONA_SOURCES", True),
        tools_enable_time=_bool(env, "TOOLS_ENABLE_TIME", True),
```

- [ ] **Step 5: Implement persona source parsing**

In `qq_rolebot/persona.py`, add:

```python
@dataclass(frozen=True)
class PersonaSource:
    name: str
    url: str
    purpose: str = ""
```

Add `sources` to `Persona`:

```python
    sources: list[PersonaSource] = field(default_factory=list)
```

Add this helper:

```python
def _sources(value: Any) -> list[PersonaSource]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Sources must be a list")

    sources: list[PersonaSource] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each source must be a mapping")
        name = _text(item, "name")
        url = _text(item, "url")
        if not name or not url:
            raise ValueError("each source must include name and url")
        sources.append(PersonaSource(name=name, url=url, purpose=_text(item, "purpose")))
    return sources
```

In `_load_roleplay_persona`, pass:

```python
        sources=_sources(data.get("Sources")),
```

For old-format personas, pass:

```python
        sources=_sources(data.get("Sources")),
```

- [ ] **Step 6: Add PRTS source to the persona file**

Append this block to `personas/default.yaml`:

```yaml
Sources:
  - name: PRTS Chongyue
    url: https://prts.wiki/w/%E9%87%8D%E5%B2%B3
    purpose: character profile, voice records, archive, and line-style reference
```

Use an editor or `apply_patch`; do not write the Tavily key to this file.

- [ ] **Step 7: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_config.py tests/test_persona_prompt_guardrails.py -q
```

Expected: PASS.

- [ ] **Step 8: Checkpoint**

Run:

```powershell
git status --short
```

Expected in current workspace: `fatal: not a git repository`. If git exists, run:

```bash
git add qq_rolebot/config.py qq_rolebot/persona.py personas/default.yaml tests/test_config.py tests/test_persona_prompt_guardrails.py
git commit -m "feat: add tool config and persona sources"
```

---

### Task 2: Incoming Addressing And Message Segment Summaries

**Files:**
- Modify: `qq_rolebot/policy.py`
- Create: `qq_rolebot/message_segments.py`
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_message_segments.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing message segment tests**

Create `tests/test_message_segments.py`:

```python
from types import SimpleNamespace

from qq_rolebot.message_segments import is_reply_to, summarize_segments


def segment(segment_type: str, **data):
    return SimpleNamespace(type=segment_type, data=data)


def test_summarize_segments_keeps_text_and_media_markers() -> None:
    message = [
        segment("text", text="hello "),
        segment("image", file="a.jpg"),
        segment("record", file="voice.amr"),
        segment("face", id="14"),
        segment("file", name="report.pdf"),
        segment("json", data="{}"),
    ]

    assert summarize_segments(message) == (
        "hello [image: a.jpg] [voice: voice.amr] [emoji: 14] "
        "[file: report.pdf] [unsupported segment: json]"
    )


def test_is_reply_to_detects_reply_segment() -> None:
    message = [segment("reply", id="12345"), segment("text", text="question")]

    assert is_reply_to(message) is True
```

- [ ] **Step 2: Write failing plugin reply test**

Append this test to `tests/test_plugin_smoke.py`:

```python
def test_plugin_marks_reply_to_bot(monkeypatch) -> None:
    set_env(monkeypatch)
    module = importlib.import_module("qq_rolebot.plugins.roleplay_chat")
    event = SimpleNamespace(
        message_type="group",
        group_id=20,
        user_id=99,
        sender=SimpleNamespace(nickname="Amy", card=""),
        time=123,
        message=[
            SimpleNamespace(type="reply", data={"id": "123"}),
            SimpleNamespace(type="text", data={"text": "today news"}),
        ],
        get_plaintext=lambda: "today news",
    )

    incoming = module.build_incoming_message(event, bot_id=10001)

    assert incoming.is_reply_to_bot is True
    assert incoming.text == "today news"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_message_segments.py tests/test_plugin_smoke.py -q
```

Expected: FAIL because `qq_rolebot.message_segments` and `IncomingMessage.is_reply_to_bot` do not exist.

- [ ] **Step 4: Add reply metadata to policy**

In `qq_rolebot/policy.py`, extend `IncomingMessage`:

```python
    is_reply_to_bot: bool = False
```

- [ ] **Step 5: Implement message segment helpers**

Create `qq_rolebot/message_segments.py`:

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _data(segment: Any) -> dict[str, Any]:
    data = getattr(segment, "data", {})
    return data if isinstance(data, dict) else {}


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def summarize_segments(message: Iterable[Any]) -> str:
    parts: list[str] = []
    for segment in message:
        segment_type = str(getattr(segment, "type", "unknown"))
        data = _data(segment)
        if segment_type == "text":
            parts.append(str(data.get("text", "")))
        elif segment_type == "at":
            qq = _first_value(data, ("qq",))
            parts.append(f"[@{qq}]" if qq else "[@]")
        elif segment_type == "reply":
            continue
        elif segment_type == "image":
            label = _first_value(data, ("file", "url", "summary"))
            parts.append(f"[image: {label}]" if label else "[image]")
        elif segment_type == "record":
            label = _first_value(data, ("file", "url", "summary"))
            parts.append(f"[voice: {label}]" if label else "[voice]")
        elif segment_type == "face":
            label = _first_value(data, ("id", "name"))
            parts.append(f"[emoji: {label}]" if label else "[emoji]")
        elif segment_type in {"file", "offline_file"}:
            label = _first_value(data, ("name", "file", "url"))
            parts.append(f"[file: {label}]" if label else "[file]")
        else:
            parts.append(f"[unsupported segment: {segment_type}]")
    return " ".join("".join(parts).split())


def is_reply_to(message: Iterable[Any]) -> bool:
    return any(str(getattr(segment, "type", "")) == "reply" for segment in message)
```

- [ ] **Step 6: Wire plugin extraction**

In `qq_rolebot/plugins/roleplay_chat.py`, import:

```python
from qq_rolebot.message_segments import is_reply_to, summarize_segments
```

Replace `extract_message_text` with:

```python
def extract_message_text(event: MessageEvent) -> str:
    message = getattr(event, "message", None)
    if message is None:
        return event.get_plaintext().strip()
    text = summarize_segments(message).strip()
    return text or event.get_plaintext().strip()
```

When constructing group `IncomingMessage`, pass:

```python
            is_reply_to_bot=is_reply_to(getattr(event, "message", [])),
```

When constructing private `IncomingMessage`, pass:

```python
            is_reply_to_bot=False,
```

- [ ] **Step 7: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_message_segments.py tests/test_plugin_smoke.py -q
```

Expected: PASS.

- [ ] **Step 8: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/policy.py qq_rolebot/message_segments.py qq_rolebot/plugins/roleplay_chat.py tests/test_message_segments.py tests/test_plugin_smoke.py
git commit -m "feat: summarize onebot message segments"
```

---

### Task 3: Tool Routing And Current Time

**Files:**
- Create: `qq_rolebot/tool_router.py`
- Create: `qq_rolebot/time_tool.py`
- Test: `tests/test_tool_router.py`
- Test: `tests/test_time_tool.py`

- [ ] **Step 1: Write failing router tests**

Create `tests/test_tool_router.py`:

```python
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.tool_router import ToolKind, ToolRouter


def msg(text: str, *, private: bool = False, at: bool = False, reply: bool = False):
    return IncomingMessage(
        group_id=0 if private else 20,
        user_id=99,
        nickname="Amy",
        text=text,
        is_at_bot=at,
        is_private=private,
        is_reply_to_bot=reply,
        created_at=100,
    )


def test_private_today_news_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\\u4eca\\u5929\\u65b0\\u95fb", private=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_group_unaddressed_today_news_does_not_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\\u4eca\\u5929\\u65b0\\u95fb"), now=100)

    assert ToolKind.SEARCH not in plan.kinds


def test_group_mention_today_news_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\\u4eca\\u5929\\u65b0\\u95fb", at=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_group_reply_latest_weather_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\\u6700\\u65b0\\u5929\\u6c14", reply=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_time_query_routes_to_time_not_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\\u73b0\\u5728\\u51e0\\u70b9", private=True), now=100)

    assert ToolKind.TIME in plan.kinds
    assert ToolKind.SEARCH not in plan.kinds


def test_role_question_routes_to_persona_source() -> None:
    router = ToolRouter(search_cooldown_seconds=20, persona_names=["Chongyue", "\\u91cd\\u5cb3"])

    plan = router.plan(msg("\\u4f60\\u7684\\u6863\\u6848", private=True), now=100)

    assert ToolKind.PERSONA_SOURCE in plan.kinds


def test_search_cooldown_blocks_repeated_open_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)
    first = router.plan(msg("\\u4eca\\u5929\\u65b0\\u95fb", private=True), now=100)
    router.record(msg("\\u4eca\\u5929\\u65b0\\u95fb", private=True), first, now=100)

    second = router.plan(msg("\\u4eca\\u5929\\u65b0\\u95fb", private=True), now=110)

    assert ToolKind.SEARCH not in second.kinds
```

- [ ] **Step 2: Write failing time tests**

Create `tests/test_time_tool.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from qq_rolebot.time_tool import TimeTool


def test_time_tool_formats_shanghai_time() -> None:
    tool = TimeTool(timezone="Asia/Shanghai")
    now = datetime(2026, 7, 6, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    reply = tool.reply(now=now)

    assert "2026-07-06" in reply
    assert "09:30" in reply
    assert "Asia/Shanghai" in reply
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tool_router.py tests/test_time_tool.py -q
```

Expected: FAIL because `tool_router.py` and `time_tool.py` do not exist.

- [ ] **Step 4: Implement tool router**

Create `qq_rolebot/tool_router.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from qq_rolebot.policy import IncomingMessage


class ToolKind(StrEnum):
    TIME = "time"
    SEARCH = "search"
    PERSONA_SOURCE = "persona_source"


@dataclass(frozen=True)
class ToolPlan:
    kinds: tuple[ToolKind, ...]
    query: str
    addressed: bool


SEARCH_KEYWORDS = (
    "search",
    "look up",
    "latest",
    "today",
    "now",
    "news",
    "weather",
    "price",
    "recent",
    "\u67e5\u4e00\u4e0b",
    "\u641c\u4e00\u4e0b",
    "\u5e2e\u6211\u67e5",
    "\u641c\u7d22",
    "\u7f51\u4e0a\u8bf4",
    "\u8d44\u6599",
    "\u5b98\u7f51",
    "\u662f\u771f\u7684\u5417",
    "\u600e\u4e48\u56de\u4e8b",
    "\u4eca\u5929",
    "\u73b0\u5728",
    "\u6700\u65b0",
    "\u65b0\u95fb",
    "\u5929\u6c14",
    "\u4ef7\u683c",
    "\u6700\u8fd1",
    "\u521a\u521a",
    "\u4eca\u5e74",
    "\u672c\u5468",
)

TIME_KEYWORDS = (
    "time",
    "date",
    "\u51e0\u70b9",
    "\u65f6\u95f4",
    "\u51e0\u53f7",
    "\u661f\u671f\u51e0",
)

PERSONA_KEYWORDS = (
    "who are you",
    "background",
    "archive",
    "voice line",
    "lore",
    "nian",
    "dusk",
    "ling",
    "yumen",
    "\u4f60\u662f\u8c01",
    "\u7ecf\u5386",
    "\u6863\u6848",
    "\u8bed\u97f3",
    "\u53f0\u8bcd",
    "\u5e74",
    "\u5915",
    "\u4ee4",
    "\u7389\u95e8",
    "\u8bbe\u5b9a",
)


class ToolRouter:
    def __init__(
        self,
        *,
        search_cooldown_seconds: int,
        persona_names: list[str] | None = None,
    ) -> None:
        self.search_cooldown_seconds = search_cooldown_seconds
        self.persona_names = [name.lower() for name in persona_names or [] if name]
        self._last_search_by_scope: dict[tuple[int, int], int] = {}

    def plan(self, message: IncomingMessage, *, now: int) -> ToolPlan:
        text = message.text.strip()
        lowered = text.lower()
        addressed = message.is_private or message.is_at_bot or message.is_reply_to_bot
        kinds: list[ToolKind] = []

        if addressed and self._contains(lowered, TIME_KEYWORDS):
            kinds.append(ToolKind.TIME)
            return ToolPlan(kinds=tuple(kinds), query=text, addressed=addressed)

        if addressed and self._contains(lowered, SEARCH_KEYWORDS) and self._search_allowed(message, now):
            kinds.append(ToolKind.SEARCH)

        role_related = addressed or any(name in lowered for name in self.persona_names)
        if role_related and self._contains(lowered, PERSONA_KEYWORDS):
            kinds.append(ToolKind.PERSONA_SOURCE)

        return ToolPlan(kinds=tuple(kinds), query=text, addressed=addressed)

    def record(self, message: IncomingMessage, plan: ToolPlan, *, now: int) -> None:
        if ToolKind.SEARCH in plan.kinds:
            self._last_search_by_scope[self._scope(message)] = now

    def _search_allowed(self, message: IncomingMessage, now: int) -> bool:
        last = self._last_search_by_scope.get(self._scope(message))
        return last is None or now - last >= self.search_cooldown_seconds

    @staticmethod
    def _scope(message: IncomingMessage) -> tuple[int, int]:
        return (message.group_id, message.user_id)

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)
```

- [ ] **Step 5: Implement time tool**

Create `qq_rolebot/time_tool.py`:

```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class TimeTool:
    def __init__(self, *, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = timezone

    def reply(self, *, now: datetime | None = None) -> str:
        zone = ZoneInfo(self.timezone)
        current = now.astimezone(zone) if now is not None else datetime.now(zone)
        return f"Current time: {current:%Y-%m-%d %H:%M:%S} ({self.timezone})."
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tool_router.py tests/test_time_tool.py -q
```

Expected: PASS.

- [ ] **Step 7: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/tool_router.py qq_rolebot/time_tool.py tests/test_tool_router.py tests/test_time_tool.py
git commit -m "feat: add tool routing and time replies"
```

---

### Task 4: Tavily Search Client

**Files:**
- Create: `qq_rolebot/tavily.py`
- Test: `tests/test_tavily.py`

- [ ] **Step 1: Write failing Tavily tests**

Create `tests/test_tavily.py`:

```python
import httpx
import pytest

from qq_rolebot.tavily import TavilyClient


@pytest.mark.asyncio
async def test_tavily_client_formats_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        payload = {
            "answer": "Short answer",
            "results": [
                {
                    "title": "Result One",
                    "url": "https://example.test/one",
                    "content": "Useful snippet.",
                }
            ],
        }
        return httpx.Response(200, json=payload)

    client = TavilyClient(
        api_key="key",
        api_base="https://api.tavily.com",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("query", max_results=3)

    assert result.ok is True
    assert result.answer == "Short answer"
    assert result.results[0].title == "Result One"
    assert result.format_context().startswith("Search query: query")


@pytest.mark.asyncio
async def test_tavily_client_handles_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "bad"})

    client = TavilyClient(
        api_key="key",
        api_base="https://api.tavily.com",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.search("query", max_results=3)

    assert result.ok is False
    assert result.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tavily.py -q
```

Expected: FAIL because `qq_rolebot.tavily` does not exist.

- [ ] **Step 3: Implement Tavily client**

Create `qq_rolebot/tavily.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class SearchItem:
    title: str
    url: str
    content: str


@dataclass(frozen=True)
class SearchResponse:
    ok: bool
    query: str
    answer: str = ""
    results: list[SearchItem] | None = None
    error: str = ""

    def format_context(self) -> str:
        if not self.ok:
            return f"Search query: {self.query}\nSearch failed: {self.error}"
        lines = [f"Search query: {self.query}"]
        if self.answer:
            lines.append(f"Answer: {self.answer}")
        for index, item in enumerate(self.results or [], start=1):
            lines.append(f"{index}. {item.title}\nURL: {item.url}\nSnippet: {item.content}")
        if len(lines) == 1:
            lines.append("No current search results were found.")
        return "\n".join(lines)


class TavilyClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str,
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def search(self, query: str, *, max_results: int) -> SearchResponse:
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{self.api_base}/search", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return SearchResponse(ok=False, query=query, error=str(exc))

        results = [
            SearchItem(
                title=str(item.get("title", "")),
                url=str(item.get("url", "")),
                content=str(item.get("content", "")),
            )
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]
        return SearchResponse(
            ok=True,
            query=query,
            answer=str(data.get("answer", "") or ""),
            results=results,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tavily.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/tavily.py tests/test_tavily.py
git commit -m "feat: add tavily search client"
```

---

### Task 5: Persona Source Client

**Files:**
- Create: `qq_rolebot/persona_sources.py`
- Test: `tests/test_persona_sources.py`

- [ ] **Step 1: Write failing persona source tests**

Create `tests/test_persona_sources.py`:

```python
import httpx
import pytest

from qq_rolebot.persona import PersonaSource
from qq_rolebot.persona_sources import PersonaSourceClient


@pytest.mark.asyncio
async def test_persona_source_fetches_allowlisted_url() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><h1>Chongyue</h1><p>Archive text.</p></body></html>",
        )

    source = PersonaSource(
        name="PRTS Chongyue",
        url="https://prts.wiki/w/%E9%87%8D%E5%B2%B3",
        purpose="character profile",
    )
    client = PersonaSourceClient(
        sources=[source],
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.lookup("archive")

    assert result.ok is True
    assert "PRTS Chongyue" in result.format_context()
    assert "Archive text." in result.format_context()


@pytest.mark.asyncio
async def test_persona_source_returns_empty_when_no_sources() -> None:
    client = PersonaSourceClient(sources=[], timeout_seconds=5)

    result = await client.lookup("archive")

    assert result.ok is False
    assert result.error == "no persona sources configured"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_persona_sources.py -q
```

Expected: FAIL because `qq_rolebot.persona_sources` does not exist.

- [ ] **Step 3: Implement persona source client**

Create `qq_rolebot/persona_sources.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from qq_rolebot.persona import PersonaSource


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


@dataclass(frozen=True)
class PersonaSourceResponse:
    ok: bool
    name: str = ""
    url: str = ""
    text: str = ""
    error: str = ""

    def format_context(self) -> str:
        if not self.ok:
            return f"Persona source failed: {self.error}"
        return f"Persona source: {self.name}\nURL: {self.url}\nExcerpt: {self.text}"


class PersonaSourceClient:
    def __init__(
        self,
        *,
        sources: list[PersonaSource],
        timeout_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
        max_chars: int = 1200,
    ) -> None:
        self.sources = sources
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.max_chars = max_chars
        self._cache: dict[str, PersonaSourceResponse] = {}

    async def lookup(self, query: str) -> PersonaSourceResponse:
        if not self.sources:
            return PersonaSourceResponse(ok=False, error="no persona sources configured")
        source = self.sources[0]
        if source.url in self._cache:
            return self._cache[source.url]
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
                follow_redirects=True,
            ) as client:
                response = await client.get(source.url)
                response.raise_for_status()
        except Exception as exc:
            return PersonaSourceResponse(ok=False, error=str(exc))

        parser = _TextExtractor()
        parser.feed(response.text)
        text = parser.text()[: self.max_chars]
        result = PersonaSourceResponse(ok=True, name=source.name, url=source.url, text=text)
        self._cache[source.url] = result
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_persona_sources.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/persona_sources.py tests/test_persona_sources.py
git commit -m "feat: add persona source lookup"
```

---

### Task 6: Tool Runner And Prompt Context

**Files:**
- Create: `qq_rolebot/tool_runner.py`
- Modify: `qq_rolebot/prompting.py`
- Test: `tests/test_tool_runner.py`
- Test: `tests/test_persona_prompt_guardrails.py`

- [ ] **Step 1: Write failing tool runner tests**

Create `tests/test_tool_runner.py`:

```python
import pytest

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolRouter
from qq_rolebot.tool_runner import ToolRunner


class FakeSearch:
    async def search(self, query: str, *, max_results: int):
        class Result:
            ok = True

            def format_context(self):
                return f"search context for {query}"

        return Result()


class FakePersonaSources:
    async def lookup(self, query: str):
        class Result:
            ok = True

            def format_context(self):
                return f"persona context for {query}"

        return Result()


def msg(text: str):
    return IncomingMessage(
        group_id=0,
        user_id=99,
        nickname="Amy",
        text=text,
        is_at_bot=False,
        is_private=True,
        created_at=100,
    )


@pytest.mark.asyncio
async def test_tool_runner_returns_direct_time_reply() -> None:
    runner = ToolRunner(
        router=ToolRouter(search_cooldown_seconds=20),
        time_tool=TimeTool(timezone="Asia/Shanghai"),
        search_client=FakeSearch(),
        persona_source_client=FakePersonaSources(),
        search_max_results=3,
        enable_time=True,
        enable_search=True,
        enable_persona_sources=True,
    )

    result = await runner.run(msg("\\u73b0\\u5728\\u51e0\\u70b9"))

    assert result.direct_reply
    assert "Current time:" in result.direct_reply


@pytest.mark.asyncio
async def test_tool_runner_returns_search_context() -> None:
    runner = ToolRunner(
        router=ToolRouter(search_cooldown_seconds=20),
        time_tool=TimeTool(timezone="Asia/Shanghai"),
        search_client=FakeSearch(),
        persona_source_client=FakePersonaSources(),
        search_max_results=3,
        enable_time=True,
        enable_search=True,
        enable_persona_sources=True,
    )

    result = await runner.run(msg("\\u4eca\\u5929\\u65b0\\u95fb"))

    assert result.direct_reply is None
    assert "search context" in result.context
```

- [ ] **Step 2: Write failing prompt test**

Append to `tests/test_persona_prompt_guardrails.py`:

```python
def test_build_chat_messages_includes_tool_context() -> None:
    persona = load_persona(Path("personas/default.yaml"))
    trigger = IncomingMessage(
        group_id=1,
        user_id=2,
        nickname="Amy",
        text="today news",
        is_at_bot=True,
        created_at=10,
    )

    messages = build_chat_messages(persona, [], trigger, tool_context="Search query: today news")

    assert "Tool Context:" in messages[0]["content"]
    assert "Search query: today news" in messages[0]["content"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tool_runner.py tests/test_persona_prompt_guardrails.py -q
```

Expected: FAIL because `tool_runner.py` does not exist and `build_chat_messages` has no `tool_context` parameter.

- [ ] **Step 4: Implement tool runner**

Create `qq_rolebot/tool_runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolKind, ToolRouter


class SearchClient(Protocol):
    async def search(self, query: str, *, max_results: int):
        ...


class PersonaSourceLookup(Protocol):
    async def lookup(self, query: str):
        ...


@dataclass(frozen=True)
class ToolRunResult:
    direct_reply: str | None = None
    context: str = ""


class ToolRunner:
    def __init__(
        self,
        *,
        router: ToolRouter,
        time_tool: TimeTool,
        search_client: SearchClient | None,
        persona_source_client: PersonaSourceLookup | None,
        search_max_results: int,
        enable_time: bool,
        enable_search: bool,
        enable_persona_sources: bool,
    ) -> None:
        self.router = router
        self.time_tool = time_tool
        self.search_client = search_client
        self.persona_source_client = persona_source_client
        self.search_max_results = search_max_results
        self.enable_time = enable_time
        self.enable_search = enable_search
        self.enable_persona_sources = enable_persona_sources

    async def run(self, message: IncomingMessage) -> ToolRunResult:
        plan = self.router.plan(message, now=message.created_at)

        if self.enable_time and ToolKind.TIME in plan.kinds:
            return ToolRunResult(direct_reply=self.time_tool.reply())

        contexts: list[str] = []
        if self.enable_search and ToolKind.SEARCH in plan.kinds and self.search_client is not None:
            search = await self.search_client.search(plan.query, max_results=self.search_max_results)
            contexts.append(search.format_context())
            self.router.record(message, plan, now=message.created_at)

        if (
            self.enable_persona_sources
            and ToolKind.PERSONA_SOURCE in plan.kinds
            and self.persona_source_client is not None
        ):
            persona_source = await self.persona_source_client.lookup(plan.query)
            contexts.append(persona_source.format_context())

        return ToolRunResult(context="\n\n".join(contexts))
```

- [ ] **Step 5: Add prompt tool context**

Change `build_chat_messages` signature in `qq_rolebot/prompting.py`:

```python
def build_chat_messages(
    persona: Persona,
    context: list[MessageRecord],
    trigger: IncomingMessage,
    *,
    tool_context: str = "",
) -> list[dict[str, str]]:
```

Add this item before `"Reply as a casual group member."`:

```python
            _section("Tool Context", tool_context),
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_tool_runner.py tests/test_persona_prompt_guardrails.py -q
```

Expected: PASS.

- [ ] **Step 7: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/tool_runner.py qq_rolebot/prompting.py tests/test_tool_runner.py tests/test_persona_prompt_guardrails.py
git commit -m "feat: add tool runner prompt context"
```

---

### Task 7: Service Integration

**Files:**
- Modify: `qq_rolebot/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/test_service.py`:

```python
class CapturingModel:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        self.messages = messages
        return ModelResult(ok=True, text="model reply")


class FakeToolRunner:
    def __init__(self, *, direct_reply: str | None = None, context: str = "") -> None:
        self.direct_reply = direct_reply
        self.context = context
        self.calls = 0

    async def run(self, message: IncomingMessage):
        self.calls += 1

        class Result:
            def __init__(self, direct_reply: str | None, context: str) -> None:
                self.direct_reply = direct_reply
                self.context = context

        return Result(self.direct_reply, self.context)


@pytest.mark.asyncio
async def test_service_returns_direct_tool_reply(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    tools = FakeToolRunner(direct_reply="Current time: 2026-07-06 09:30:00 (Asia/Shanghai).")
    service = ChatService(
        settings=settings,
        storage=storage,
        model=CapturingModel(),
        rate_limiter=RateLimiter(),
        tool_runner=tools,
    )

    reply = await service.handle(private_msg("\\u73b0\\u5728\\u51e0\\u70b9"), random_value=99)

    assert reply == "Current time: 2026-07-06 09:30:00 (Asia/Shanghai)."
    assert tools.calls == 1


@pytest.mark.asyncio
async def test_service_passes_tool_context_to_model(tmp_path: Path) -> None:
    settings = load_settings(env(tmp_path))
    storage = Storage(settings.database_path)
    await storage.init()
    model = CapturingModel()
    service = ChatService(
        settings=settings,
        storage=storage,
        model=model,
        rate_limiter=RateLimiter(),
        tool_runner=FakeToolRunner(context="Search query: today news"),
    )

    reply = await service.handle(private_msg("today news"), random_value=99)

    assert reply == "model reply"
    assert "Search query: today news" in model.messages[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_service.py -q
```

Expected: FAIL because `ChatService.__init__` has no `tool_runner` parameter.

- [ ] **Step 3: Add service protocol and constructor parameter**

In `qq_rolebot/service.py`, add:

```python
class ToolRunnerProtocol(Protocol):
    async def run(self, message: IncomingMessage):
        ...
```

Add to `ChatService.__init__`:

```python
        tool_runner: ToolRunnerProtocol | None = None,
```

Store:

```python
        self.tool_runner = tool_runner
```

- [ ] **Step 4: Invoke tools in group and private flows**

In both the group model-call block and `_handle_private`, before fetching context for the model, add:

```python
        tool_context = ""
        if self.tool_runner is not None:
            tool_result = await self.tool_runner.run(message)
            if getattr(tool_result, "direct_reply", None):
                reply = clean_response(
                    tool_result.direct_reply,
                    max_chars=self.settings.max_output_chars,
                    sensitive_words=self.settings.sensitive_words,
                )
                if reply is not None:
                    self.rate_limiter.record(message.group_id, message.user_id, now=message.created_at)
                return reply
            tool_context = str(getattr(tool_result, "context", "") or "")
```

For private context, use `context_id` when recording direct replies:

```python
                    self.rate_limiter.record(context_id, message.user_id, now=message.created_at)
```

Pass tool context into the model prompt:

```python
        result = await self.model.chat(
            build_chat_messages(self.persona, context, message, tool_context=tool_context)
        )
```

- [ ] **Step 5: Run service tests**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/service.py tests/test_service.py
git commit -m "feat: integrate tool runner with chat service"
```

---

### Task 8: Plugin Wiring And Runtime Clients

**Files:**
- Modify: `qq_rolebot/plugins/roleplay_chat.py`
- Test: `tests/test_plugin_smoke.py`

- [ ] **Step 1: Write failing plugin wiring test**

Append to `tests/test_plugin_smoke.py`:

```python
def test_roleplay_plugin_builds_tool_runner(monkeypatch) -> None:
    set_env(monkeypatch)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    module = importlib.reload(importlib.import_module("qq_rolebot.plugins.roleplay_chat"))

    assert module.service.tool_runner is not None
```

- [ ] **Step 2: Run plugin tests to verify they fail**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_plugin_smoke.py -q
```

Expected: FAIL because plugin does not create a tool runner.

- [ ] **Step 3: Wire clients into plugin**

In `qq_rolebot/plugins/roleplay_chat.py`, import:

```python
from qq_rolebot.persona import load_persona
from qq_rolebot.persona_sources import PersonaSourceClient
from qq_rolebot.tavily import TavilyClient
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolRouter
from qq_rolebot.tool_runner import ToolRunner
```

Before `service = ChatService(...)`, build tools:

```python
persona = load_persona(settings.persona_path)
search_client = None
if settings.tavily_api_key:
    search_client = TavilyClient(
        api_key=settings.tavily_api_key,
        api_base=settings.tavily_api_base,
        timeout_seconds=settings.search_timeout_seconds,
    )

persona_source_client = PersonaSourceClient(
    sources=persona.sources,
    timeout_seconds=settings.search_timeout_seconds,
)

tool_runner = ToolRunner(
    router=ToolRouter(
        search_cooldown_seconds=settings.search_cooldown_seconds,
        persona_names=[persona.name, "Chongyue", "\u91cd\u5cb3"],
    ),
    time_tool=TimeTool(timezone="Asia/Shanghai"),
    search_client=search_client,
    persona_source_client=persona_source_client,
    search_max_results=settings.search_max_results,
    enable_time=settings.tools_enable_time,
    enable_search=settings.tools_enable_search and search_client is not None,
    enable_persona_sources=settings.tools_enable_persona_sources,
)
```

Pass into `ChatService`:

```python
    tool_runner=tool_runner,
```

- [ ] **Step 4: Run plugin tests**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest tests/test_plugin_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add qq_rolebot/plugins/roleplay_chat.py tests/test_plugin_smoke.py
git commit -m "feat: wire rolebot tool clients"
```

---

### Task 9: Documentation And Environment Examples

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [ ] **Step 1: Update `.env.example` without secrets**

Add:

```dotenv
TAVILY_API_KEY=
TAVILY_API_BASE=https://api.tavily.com
SEARCH_MAX_RESULTS=5
SEARCH_TIMEOUT_SECONDS=10
SEARCH_COOLDOWN_SECONDS=20
TOOLS_ENABLE_SEARCH=true
TOOLS_ENABLE_PERSONA_SOURCES=true
TOOLS_ENABLE_TIME=true
```

- [ ] **Step 2: Update `README.md`**

Add a short section:

```markdown
## Tools

The bot can answer current-time questions directly and can use Tavily search when a private
message or explicitly addressed group message asks for current external information.

Set `TAVILY_API_KEY` in `.env` to enable web search. Do not commit real API keys.
Persona source lookup reads the `Sources` list from `personas/default.yaml`.
```

- [ ] **Step 3: Update `docs/deployment.md`**

Add:

```markdown
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
```

- [ ] **Step 4: Check docs for accidental secrets**

Run:

```powershell
rg -n "tvly|TAVILY_API_KEY=.*[A-Za-z0-9_-]{12,}" .env.example README.md docs
```

Expected: no output containing the real key.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git status --short
```

If git exists:

```bash
git add .env.example README.md docs/deployment.md
git commit -m "docs: document rolebot tools config"
```

---

### Task 10: Full Local Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all tests**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run ruff**

Run:

```powershell
D:\Anaconda\envs\qq-rolebot\python.exe -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Confirm no real Tavily key in the workspace**

Run:

```powershell
rg -n "tvly" .
```

Expected: no output.

- [ ] **Step 4: Checkpoint**

Run:

```powershell
git status --short
```

If git exists and there are remaining tracked changes:

```bash
git add .
git commit -m "test: verify rolebot tools integration"
```

---

### Task 11: Server Deployment

**Files:**
- Server: `/opt/qq-rolebot/.env`
- Server: `/opt/qq-rolebot`

- [ ] **Step 1: Add Tavily key to server environment**

Use SSH or the existing Paramiko deployment helper style. Add `TAVILY_API_KEY` to
`/opt/qq-rolebot/.env` using the secret value supplied by the user:

```dotenv
TAVILY_API_KEY=
```

Fill the value on the server only. Do not print it in logs. If scripting, print only the key
length.

- [ ] **Step 2: Upload changed project files**

Upload modified code, tests, docs, and `personas/default.yaml` to `/opt/qq-rolebot`. Preserve a timestamped backup of overwritten server files:

```bash
cp -a /opt/qq-rolebot /opt/qq-rolebot.bak-$(date +%Y%m%d%H%M%S)
```

If using file-by-file upload, back up each overwritten file with `.bak-YYYYmmddHHMMSS`.

- [ ] **Step 3: Run server tests**

Run on server:

```bash
cd /opt/qq-rolebot
/opt/miniconda3/envs/qq-rolebot/bin/python -m pytest -q
/opt/miniconda3/envs/qq-rolebot/bin/python -m ruff check .
```

Expected: all tests pass and ruff reports all checks passed.

- [ ] **Step 4: Restart service**

Run:

```bash
systemctl restart qq-rolebot
sleep 35
systemctl is-active qq-rolebot
journalctl -u qq-rolebot -n 100 --no-pager
```

Expected:

- `systemctl is-active` prints `active`.
- Logs include `Succeeded to load plugin "roleplay_chat"`.
- Logs include `Bot 3961601898 connected` after NapCat reconnects.

- [ ] **Step 5: Manual smoke tests in QQ**

Send these messages:

1. Private chat: "today news"
   - Expected: bot uses search context and replies in persona.
2. Group chat without mention: "today news"
   - Expected: no search-triggered reply.
3. Group chat with mention: `@bot today news`
   - Expected: search-triggered reply.
4. Private chat: "what time is it"
   - Expected: direct current-time reply.
5. Private chat: "your archive"
   - Expected: persona-source context can be used.

Use equivalent Chinese phrases in real QQ testing.

---

## Self-Review

### Spec Coverage

- Current time queries: Task 3, Task 6, Task 7, Task 11.
- Tavily search: Task 1, Task 3, Task 4, Task 6, Task 7, Task 8, Task 11.
- Persona source lookup and PRTS URL: Task 1, Task 5, Task 6, Task 8, Task 11.
- Prompt tool context: Task 6 and Task 7.
- Media recognition summaries: Task 2.
- Voice/TTS safety boundaries: documented as out of scope for this first slice and preserved by typed-response direction in the spec; no voice assets are added.
- Secret handling: Task 1, Task 9, Task 10, Task 11.

### Placeholder Scan

This plan uses concrete file paths, command lines, expected failures, and implementation snippets.
It does not include placeholder implementation steps or real API keys.

### Type Consistency

- `IncomingMessage.is_reply_to_bot` is introduced in Task 2 and consumed by `ToolRouter` in Task 3.
- `PersonaSource` and `Persona.sources` are introduced in Task 1 and consumed by `PersonaSourceClient` in Task 5 and plugin wiring in Task 8.
- `ToolPlan`, `ToolKind`, and `ToolRunner` are introduced before service/plugin integration.
- `build_chat_messages(..., tool_context="")` is introduced before `ChatService` passes tool context.
