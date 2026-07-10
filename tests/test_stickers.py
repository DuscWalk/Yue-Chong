from pathlib import Path

from qq_rolebot.stickers import StickerLibrary


def test_sticker_library_loads_existing_manifest_item(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    (root / "chongyue").mkdir(parents=True)
    image = root / "chongyue" / "calm.webp"
    image.write_bytes(b"image")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: calm
    file: chongyue/calm.webp
    tags: [calm, reply]
    weight: 2
""".strip(),
        encoding="utf-8",
    )

    library = StickerLibrary(root=root, manifest_path=manifest)

    item = library.select(tags=["reply"], random_value=0)

    assert item is not None
    assert item.id == "calm"
    assert item.path == image


def test_sticker_library_skips_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: missing
    file: missing.webp
    tags: [reply]
    weight: 1
""".strip(),
        encoding="utf-8",
    )

    library = StickerLibrary(root=root, manifest_path=manifest)

    assert library.select(tags=["reply"], random_value=0) is None


def test_sticker_library_missing_manifest_is_empty(tmp_path: Path) -> None:
    library = StickerLibrary(root=tmp_path / "stickers", manifest_path=tmp_path / "none.yaml")

    assert library.select(tags=["reply"], random_value=0) is None


def test_sticker_library_loads_mface_metadata(tmp_path: Path) -> None:
    root = tmp_path / "stickers"
    root.mkdir()
    image = root / "market.webp"
    image.write_bytes(b"image")
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

    item = StickerLibrary(root=root, manifest_path=manifest).select(
        tags=["reply"],
        random_value=0,
    )

    assert item is not None
    assert item.media_type == "mface"
    assert item.is_sendable_mface is True
    assert item.emoji_id == "123"
