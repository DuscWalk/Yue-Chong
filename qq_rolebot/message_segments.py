from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _data(segment: Any) -> dict[str, Any]:
    data = getattr(segment, "data", {})
    return data if isinstance(data, dict) else {}


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def summarize_segments(message: Iterable[Any]) -> str:
    parts: list[str] = []
    for segment in message:
        segment_type = str(getattr(segment, "type", "unknown"))
        data = _data(segment)
        if segment_type == "text":
            parts.append(str(data.get("text", "")))
        elif segment_type == "at":
            qq = _first_value(data, ("qq",))
            parts.append(f"[@{qq}]" if qq else "[@]")
        elif segment_type == "reply":
            continue
        elif segment_type == "image":
            label = _first_value(data, ("file", "url", "summary"))
            parts.append(f"[image: {label}]" if label else "[image]")
        elif segment_type == "record":
            label = _first_value(data, ("file", "url", "summary"))
            parts.append(f"[voice: {label}]" if label else "[voice]")
        elif segment_type == "face":
            label = _first_value(data, ("id", "name"))
            parts.append(f"[emoji: {label}]" if label else "[emoji]")
        elif segment_type in {"file", "offline_file"}:
            label = _first_value(data, ("name", "file", "url"))
            parts.append(f"[file: {label}]" if label else "[file]")
        else:
            parts.append(f"[unsupported segment: {segment_type}]")
    return " ".join(part.strip() for part in parts if part.strip())


def is_reply_to(message: Iterable[Any]) -> bool:
    return any(str(getattr(segment, "type", "")) == "reply" for segment in message)
