from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from qq_rolebot.stickers import StickerLibrary


class CustomFaceClient(Protocol):
    async def add_custom_face(self, *, file: str, is_origin: bool = True) -> Any:
        ...

    async def fetch_custom_face_detail(self, *, count: int = 48) -> Any:
        ...


@dataclass(frozen=True)
class CustomFaceRegistrationResult:
    registered_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0


class CustomFaceRegistrar:
    def __init__(
        self,
        *,
        library: StickerLibrary,
        cache_path: Path,
        client: CustomFaceClient,
    ) -> None:
        self.library = library
        self.cache_path = cache_path
        self.client = client

    async def register_all(self) -> CustomFaceRegistrationResult:
        cache = self._load_cache()
        registered = 0
        skipped = 0
        failed = 0
        for item in self.library.items():
            if not item.path.is_file():
                continue
            digest = self._sha256(item.path)
            cached = cache.get(item.id)
            if isinstance(cached, dict) and cached.get("sha256") == digest:
                skipped += 1
                continue
            try:
                await self.client.add_custom_face(file=str(item.path), is_origin=True)
                details = await self.client.fetch_custom_face_detail(count=48)
                registered += 1
                cache[item.id] = {
                    "sha256": digest,
                    "path": str(item.path),
                    "status": "registered",
                    "detail_count": len(details) if isinstance(details, list) else None,
                }
            except Exception as exc:
                failed += 1
                cache[item.id] = {
                    "sha256": digest,
                    "path": str(item.path),
                    "status": "failed",
                    "error": exc.__class__.__name__,
                }
        self._save_cache(cache)
        return CustomFaceRegistrationResult(
            registered_count=registered,
            skipped_count=skipped,
            failed_count=failed,
        )

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(cache, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
