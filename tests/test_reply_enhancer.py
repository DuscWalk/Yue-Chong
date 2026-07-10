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


def test_reply_enhancer_never_creates_standalone_reply(tmp_path: Path) -> None:
    enhancer = ReplyEnhancer(enabled=True, probability=100, library=build_library(tmp_path))

    reply = enhancer.enhance(OutgoingReply(source="model", messages=[]), random_value=0)

    assert reply.messages == []
