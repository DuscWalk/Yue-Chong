import json
from hashlib import md5, sha256
from pathlib import Path

from qq_rolebot.custom_faces import CustomFaceRegistrar
from qq_rolebot.stickers import StickerLibrary


class FakeCustomFaceClient:
    def __init__(self, details=None):
        self.added = []
        self.details = details or []

    async def add_custom_face(self, *, file: str, is_origin: bool = True):
        self.added.append((file, is_origin))
        return {"result": 0}

    async def fetch_custom_face_detail(self, *, count: int = 48):
        return self.details


def build_library(tmp_path: Path) -> StickerLibrary:
    root = tmp_path / "stickers"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"image-a")
    (root / "b.jpg").write_bytes(b"image-b")
    manifest = root / "manifest.yaml"
    manifest.write_text(
        """
items:
  - id: a
    file: a.jpg
    type: custom_face
    tags: [reply]
  - id: b
    file: b.jpg
    type: image
    tags: [reply]
""".strip(),
        encoding="utf-8",
    )
    return StickerLibrary(root=root, manifest_path=manifest)


async def test_custom_face_registrar_adds_manifest_images_and_writes_cache(
    tmp_path: Path,
) -> None:
    client = FakeCustomFaceClient()
    cache_path = tmp_path / "custom_faces.json"
    registrar = CustomFaceRegistrar(
        library=build_library(tmp_path),
        cache_path=cache_path,
        client=client,
    )

    result = await registrar.register_all()

    assert result.registered_count == 2
    assert len(client.added) == 2
    assert cache_path.exists()


async def test_custom_face_registrar_skips_unchanged_cached_items(tmp_path: Path) -> None:
    client = FakeCustomFaceClient()
    cache_path = tmp_path / "custom_faces.json"
    registrar = CustomFaceRegistrar(
        library=build_library(tmp_path),
        cache_path=cache_path,
        client=client,
    )

    await registrar.register_all()
    client.added.clear()
    second = await registrar.register_all()

    assert second.skipped_count == 2
    assert client.added == []


async def test_custom_face_registrar_uses_existing_custom_face_detail(tmp_path: Path) -> None:
    library = build_library(tmp_path)
    existing = md5((tmp_path / "stickers" / "a.jpg").read_bytes()).hexdigest().upper()
    client = FakeCustomFaceClient(details=[{"md5": existing, "resId": "existing-id"}])
    cache_path = tmp_path / "custom_faces.json"
    registrar = CustomFaceRegistrar(
        library=library,
        cache_path=cache_path,
        client=client,
    )

    result = await registrar.register_all()

    assert result.registered_count == 2
    assert [Path(file).name for file, _ in client.added] == ["b.jpg"]
    assert '"status": "registered"' in cache_path.read_text(encoding="utf-8")


async def test_custom_face_registrar_retries_failed_cached_item(tmp_path: Path) -> None:
    library = build_library(tmp_path)
    existing = md5((tmp_path / "stickers" / "a.jpg").read_bytes()).hexdigest().upper()
    existing_sha256 = sha256((tmp_path / "stickers" / "a.jpg").read_bytes()).hexdigest()
    cache_path = tmp_path / "custom_faces.json"
    cache_path.write_text(
        json.dumps({"a": {"sha256": existing_sha256, "status": "failed"}}),
        encoding="utf-8",
    )
    client = FakeCustomFaceClient(details=[{"md5": existing, "resId": "existing-id"}])
    registrar = CustomFaceRegistrar(
        library=library,
        cache_path=cache_path,
        client=client,
    )

    await registrar.register_all()

    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert [Path(file).name for file, _ in client.added] == ["b.jpg"]
    assert cache["a"]["status"] == "registered"
