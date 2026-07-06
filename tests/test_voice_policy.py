from qq_rolebot.policy import IncomingMessage
from qq_rolebot.voice_policy import VoicePolicy


def msg(
    text: str,
    *,
    private: bool = False,
    at: bool = False,
    reply: bool = False,
    group_id: int = 20001,
    user_id: int = 10001,
) -> IncomingMessage:
    return IncomingMessage(
        group_id=0 if private else group_id,
        user_id=user_id,
        nickname="Amy",
        text=text,
        is_at_bot=at,
        is_private=private,
        is_reply_to_bot=reply,
        created_at=100,
    )


def test_private_voice_keyword_is_allowed() -> None:
    policy = VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120)

    assert policy.should_attempt(msg("用语音说一句", private=True), now=100) is True


def test_addressed_group_voice_keyword_is_allowed() -> None:
    policy = VoicePolicy(trigger_keywords=["念一下"], cooldown_seconds=120)

    assert policy.should_attempt(msg("念一下这句话", at=True), now=100) is True
    assert policy.should_attempt(msg("念一下这句话", reply=True), now=100) is True


def test_unaddressed_group_voice_keyword_is_ignored() -> None:
    policy = VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120)

    assert policy.should_attempt(msg("发个语音看看"), now=100) is False


def test_voice_policy_cooldown_blocks_same_scope() -> None:
    policy = VoicePolicy(trigger_keywords=["语音"], cooldown_seconds=120)
    message = msg("语音说一句", private=True, user_id=10001)

    assert policy.should_attempt(message, now=100) is True
    policy.record(message, now=100)

    assert policy.should_attempt(message, now=150) is False
    assert policy.should_attempt(message, now=221) is True
