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
        "[file: report.pdf]"
    )


def test_summarize_segments_omits_unknown_segments() -> None:
    message = [segment("text", text="正常文本"), segment("json", data="{}")]

    assert message_segments.summarize_segments(message) == "正常文本"


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


def test_extract_repeat_media_prefers_face_id() -> None:
    message = [segment("face", id="14")]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "face"
    assert media.face_id == "14"
    assert media.signature == "face:14"


def test_extract_repeat_media_reads_image_file_or_url() -> None:
    message = [
        segment(
            "image",
            file="abc.image",
            url="https://example.test/a.jpg",
            sub_type=0,
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "image"
    assert media.file == "abc.image"
    assert media.url == "https://example.test/a.jpg"
    assert media.image_sub_type == 0
    assert media.signature == "image:abc.image"


def test_extract_repeat_media_preserves_custom_image_metadata() -> None:
    message = [
        segment(
            "image",
            file="custom.gif",
            url="https://example.test/custom.gif",
            sub_type=1,
            summary="[动画表情]",
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "image"
    assert media.image_sub_type == 1
    assert media.summary == "[动画表情]"


def test_extract_repeat_media_marks_image_without_subtype_as_ambiguous() -> None:
    message = [segment("image", file="unknown.gif", url="https://example.test/unknown.gif")]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "image"
    assert media.image_sub_type is None


def test_extract_repeat_media_reads_mface_segment() -> None:
    message = [
        segment(
            "mface",
            emoji_id="123",
            emoji_package_id=456,
            key="send-key",
            summary="[测试表情]",
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "mface"
    assert media.emoji_id == "123"
    assert media.emoji_package_id == "456"
    assert media.key == "send-key"
    assert media.summary == "[测试表情]"
    assert media.signature == "mface:456:123:send-key"


def test_extract_repeat_media_reads_marketface_image_segment() -> None:
    message = [
        segment(
            "image",
            file="ab-123.gif",
            url="https://example.test/ab-123.gif",
            emoji_id="123",
            emoji_package_id=456,
            key="send-key",
            summary="[商城表情]",
        )
    ]

    media = message_segments.extract_repeat_media(message)

    assert media.kind == "mface"
    assert media.file == "ab-123.gif"
    assert media.url == "https://example.test/ab-123.gif"
    assert media.signature == "mface:456:123:send-key"
