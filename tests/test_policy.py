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
