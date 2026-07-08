from types import SimpleNamespace

from qq_rolebot import message_segments


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

    assert message_segments.summarize_segments(message) == (
        "hello [image: a.jpg] [voice: voice.amr] [emoji: 14] "
        "[file: report.pdf] [unsupported segment: json]"
    )


def test_is_reply_to_detects_reply_segment() -> None:
    message = [segment("reply", id="12345"), segment("text", text="question")]

    assert message_segments.is_reply_to(message) is True


def test_extract_image_urls_keeps_only_http_image_urls() -> None:
    message = [
        segment("image", url="https://example.test/a.jpg"),
        segment("image", file="http://example.test/b.jpg"),
        segment("image", file="local-cache.jpg"),
        segment("text", text="not an image"),
    ]

    assert message_segments.extract_image_urls(message) == [
        "https://example.test/a.jpg",
        "http://example.test/b.jpg",
    ]


def test_extract_media_urls_splits_static_images_and_dynamic_media() -> None:
    message = [
        segment("image", url="https://example.test/a.jpg"),
        segment("image", url="https://example.test/meme.GIF?size=large"),
        segment("video", url="https://example.test/clip.mp4"),
        segment("video", file="https://example.test/clip.mov"),
        segment("image", file="local-cache.gif"),
        segment("video", file="local-cache.mp4"),
    ]

    assert hasattr(message_segments, "extract_media_urls")
    media = message_segments.extract_media_urls(message)

    assert media.image_urls == ["https://example.test/a.jpg"]
    assert media.video_urls == [
        "https://example.test/meme.GIF?size=large",
        "https://example.test/clip.mp4",
        "https://example.test/clip.mov",
    ]


def test_extract_media_urls_keeps_media_markers() -> None:
    message = [
        segment("image", file="quoted.png", url="https://example.test/quoted.png"),
        segment("video", file="clip.mp4", url="https://example.test/clip.mp4"),
    ]

    media = message_segments.extract_media_urls(message)

    assert media.markers == ["[image: quoted.png]", "[video: clip.mp4]"]
