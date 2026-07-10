from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StickerItem:
    id: str
    path: Path
    tags: tuple[str, ...]
    weight: int = 1


class StickerLibrary:
    def __init__(self, *, root: Path, manifest_path: Path) -> None:
        self.root = root
        self.manifest_path = manifest_path
        self._items: list[StickerItem] | None = None

    def select(self, *, tags: list[str], random_value: int) -> StickerItem | None:
        items = self._matching_items(tags)
        if not items:
            return None
        total = sum(item.weight for item in items)
        if total <= 0:
            return None
        cursor = random_value % total
        for item in items:
            if cursor < item.weight:
                return item
            cursor -= item.weight
        return items[-1]

    def _matching_items(self, tags: list[str]) -> list[StickerItem]:
        wanted = {tag.strip().lower() for tag in tags if tag.strip()}
        items = self._load_items()
        if not wanted:
            return items
        return [item for item in items if wanted.intersection(item.tags)]

    def _load_items(self) -> list[StickerItem]:
        if self._items is not None:
            return self._items
        self._items = self._read_items()
        return self._items

    def _read_items(self) -> list[StickerItem]:
        if not self.manifest_path.exists():
            return []
        raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        raw_items = raw.get("items", []) if isinstance(raw, dict) else []
        items: list[StickerItem] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = self._parse_item(raw_item)
            if item is not None:
                items.append(item)
        return items

    def _parse_item(self, raw_item: dict[str, Any]) -> StickerItem | None:
        item_id = str(raw_item.get("id", "") or "").strip()
        relative_file = str(raw_item.get("file", "") or "").strip()
        if not item_id or not relative_file:
            return None
        path = self.root / relative_file
        if not path.is_file():
            return None
        raw_tags = raw_item.get("tags", [])
        tags = tuple(str(tag).strip().lower() for tag in raw_tags if str(tag).strip())
        try:
            weight = int(raw_item.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1
        return StickerItem(id=item_id, path=path, tags=tags, weight=max(1, weight))
