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
