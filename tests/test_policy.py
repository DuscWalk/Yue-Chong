from qq_rolebot.policy import (
    FollowupTracker,
    IncomingMessage,
    RateLimiter,
    TriggerKind,
    decide_trigger,
)


def message(
    text: str,
    *,
    at_bot: bool = False,
    reply_to_bot: bool = False,
    user_id: int = 10,
    created_at: int = 100,
) -> IncomingMessage:
    return IncomingMessage(
        group_id=20,
        user_id=user_id,
        nickname="tester",
        text=text,
        is_at_bot=at_bot,
        is_reply_to_bot=reply_to_bot,
        created_at=created_at,
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


def test_reply_to_bot_triggers_reply() -> None:
    decision = decide_trigger(
        message("then what", reply_to_bot=True),
        group_enabled=True,
        muted_until=0,
        keywords=[],
        random_probability=0,
        now=100,
        random_value=99,
    )

    assert decision.should_reply is True
    assert decision.kind == TriggerKind.MENTION


def test_followup_tracker_detects_addressed_followup() -> None:
    tracker = FollowupTracker(
        window_seconds=90,
        trigger_keywords=["你", "怎么看", "说话", "大哥"],
    )
    tracker.record(message("hello", at_bot=True, created_at=100), now=100)

    assert tracker.should_trigger(message("你怎么看", created_at=120), now=120) is True
    assert tracker.should_trigger(message("哈哈哈", created_at=121), now=121) is False
    assert tracker.should_trigger(message("你怎么看", user_id=11, created_at=122), now=122) is False
    assert tracker.should_trigger(message("你怎么看", created_at=191), now=191) is False


def test_followup_trigger_can_drive_decision() -> None:
    decision = decide_trigger(
        message("你怎么看"),
        group_enabled=True,
        muted_until=0,
        keywords=[],
        random_probability=0,
        now=120,
        random_value=99,
        followup_matched=True,
    )

    assert decision.should_reply is True
    assert decision.kind == TriggerKind.FOLLOWUP


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
