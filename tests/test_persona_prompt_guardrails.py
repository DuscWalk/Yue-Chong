from pathlib import Path

from qq_rolebot.guardrails import clean_response
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import IncomingMessage
from qq_rolebot.prompting import build_chat_messages
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


def test_load_persona_from_roleplay_yaml(tmp_path: Path) -> None:
    path = tmp_path / "persona.yaml"
    path.write_text(
        """
user_name: 博士
assistant_name: 重岳
language: 简体中文
Profile: |
  - 你是罗德岛的访客。
Skills: |
  - 说话沉稳从容。
Background: |
  - 你和博士通过QQ聊天。
Rules: |
  - 只输出纯文本对话内容。
Prologue: |
  博士，称呼我重岳便好。
Examples:
  - 博士问候： “晨安，博士。”
""".strip(),
        encoding="utf-8",
    )

    persona = load_persona(path)

    assert persona.name == "重岳"
    assert persona.user_name == "博士"
    assert persona.language == "简体中文"
    assert "罗德岛的访客" in persona.profile
    assert "只输出纯文本" in persona.rules
    assert persona.examples == ["博士问候： “晨安，博士。”"]


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
    assert persona.name in messages[0]["content"]
    assert "Rules:" in messages[0]["content"]
    assert "Current local time:" in messages[0]["content"]
    assert "1970-01-01 08:00:10" in messages[0]["content"]
    assert "Do not assume it is morning" in messages[0]["content"]
    assert "20 Chinese characters" in messages[0]["content"]
    assert "Recent chat context:" in messages[1]["content"]
    assert "[1970-01-01 08:00:09] Bob: good morning" in messages[1]["content"]
    assert messages[-1]["content"] == "Amy: Mika hello"


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


def test_default_dialect_persona_uses_consistent_wuhan_voice() -> None:
    persona = load_persona(Path("personas/default_dialect.yaml"))
    combined = "\n".join(
        [
            persona.language,
            persona.profile,
            persona.style,
            persona.rules,
            "\n".join(persona.examples),
        ]
    )

    assert "武汉话教学" not in combined
    assert "只是他平常讲话的底色" not in combined
    assert "莫混成四川话" not in combined
    assert "泛西南腔" not in combined
    assert "平常就这么讲" in combined
    assert "群里聊得火热" in combined


def test_default_dialect_examples_are_substantial_short_replies() -> None:
    persona = load_persona(Path("personas/default_dialect.yaml"))
    replies = [
        "".join(example.splitlines()[1:]).strip()
        for example in persona.examples
        if len(example.splitlines()) >= 2
    ]

    average_reply_length = sum(len(reply) for reply in replies) / len(replies)

    assert 14 <= average_reply_length <= 20


def test_clean_response_trims_and_limits_length() -> None:
    assert clean_response("  hello world  ", max_chars=5, sensitive_words=[]) == "hello"


def test_clean_response_suppresses_sensitive_word() -> None:
    assert (
        clean_response("this has blocked text", max_chars=100, sensitive_words=["blocked"]) is None
    )


def test_clean_response_suppresses_system_leak() -> None:
    assert clean_response("system prompt: hidden", max_chars=100, sensitive_words=[]) is None
