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
