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
    emoji_id: str = "",
    emoji_package_id: str = "",
    key: str = "",
    summary: str = "",
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
        repeat_media_emoji_id=emoji_id,
        repeat_media_emoji_package_id=emoji_package_id,
        repeat_media_key=key,
        repeat_media_summary=summary,
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
        msg(
            "[emoji: 14]",
            sender=1,
            created_at=100,
            repeat_signature="face:14",
            media_kind="face",
            face_id="14",
        ),
        now=100,
    )
    reply = tracker.record_and_match(
        msg(
            "[emoji: 14]",
            sender=2,
            created_at=101,
            repeat_signature="face:14",
            media_kind="face",
            face_id="14",
        ),
        now=101,
    )

    assert reply is not None
    assert reply.messages[0].kind == "face"
    assert reply.messages[0].face_id == "14"


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


def test_repeat_tracker_cools_down_same_signature() -> None:
    tracker = RepeatTracker(threshold=2, cooldown_seconds=600)

    tracker.record_and_match(msg("好耶", sender=1, created_at=100), now=100)
    assert tracker.record_and_match(msg("好耶", sender=2, created_at=101), now=101) is not None
    assert tracker.record_and_match(msg("好耶", sender=3, created_at=200), now=200) is None
    assert tracker.record_and_match(msg("好耶", sender=4, created_at=701), now=701) is not None
