from pathlib import Path

from qq_rolebot.outgoing import OutgoingReply
from qq_rolebot.reply_enhancer import ReplyEnhancer
from qq_rolebot.stickers import StickerLibrary


def build_library(tmp_path: Path) -> StickerLibrary:
    root = tmp_path / "stickers"
    (root / "chongyue").mkdir(parents=True)
    (root / "chongyue" / "calm.webp").write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: calm
    file: chongyue/calm.webp
    tags: [reply]
    weight: 1
""".strip(),
        encoding="utf-8",
    )
    return StickerLibrary(root=root, manifest_path=manifest)


def test_reply_enhancer_appends_sticker_after_text(tmp_path: Path) -> None:
    enhancer = ReplyEnhancer(enabled=True, probability=100, library=build_library(tmp_path))

    reply = enhancer.enhance(OutgoingReply.text("一切安好。", source="model"), random_value=0)

    assert [message.kind for message in reply.messages] == ["text", "image"]
    assert reply.messages[1].source == "sticker"
    assert reply.messages[1].image_sub_type == 1
    assert reply.messages[1].summary == "[动画表情]"


def test_reply_enhancer_never_creates_standalone_reply(tmp_path: Path) -> None:
    enhancer = ReplyEnhancer(enabled=True, probability=100, library=build_library(tmp_path))

    reply = enhancer.enhance(OutgoingReply(source="model", messages=[]), random_value=0)

    assert reply.messages == []


def test_reply_enhancer_prefers_sendable_mface(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    (root / "market.webp").write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: market
    file: market.webp
    type: mface
    emoji_id: "123"
    emoji_package_id: "456"
    key: send-key
    summary: "[测试表情]"
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )
    enhancer = ReplyEnhancer(
        enabled=True,
        probability=100,
        library=StickerLibrary(root=root, manifest_path=manifest),
    )

    reply = enhancer.enhance(OutgoingReply.text("一切安好。", source="model"), random_value=0)

    assert [message.kind for message in reply.messages] == ["text", "mface"]
    assert reply.messages[1].emoji_id == "123"
