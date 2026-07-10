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
