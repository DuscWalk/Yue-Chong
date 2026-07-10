from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

_DYNAMIC_MEDIA_EXTENSIONS = {
    ".gif",
    ".mp4",
    ".mov",
    ".webm",
    ".avi",
    ".mkv",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpeg",
    ".mpg",
}


@dataclass(frozen=True)
class MediaUrls:
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepeatMedia:
    kind: str = ""
    file: str = ""
    url: str = ""
    face_id: str = ""

    @property
    def signature(self) -> str:
        if self.kind == "face" and self.face_id:
            return f"face:{self.face_id}"
        if self.kind == "image":
            value = self.file or self.url
            return f"image:{value}" if value else ""
        return ""


def _data(segment: Any) -> dict[str, Any]:
    if isinstance(segment, dict):
        data = segment.get("data", {})
        return data if isinstance(data, dict) else {}
    data = getattr(segment, "data", {})
    return data if isinstance(data, dict) else {}


def _segment_type(segment: Any) -> str:
    if isinstance(segment, dict):
        return str(segment.get("type", "unknown"))
    return str(getattr(segment, "type", "unknown"))


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""


def _is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _is_dynamic_media_url(value: str) -> bool:
    path = urlparse(value).path.lower()
    return any(path.endswith(extension) for extension in _DYNAMIC_MEDIA_EXTENSIONS)


def summarize_segments(message: Iterable[Any]) -> str:
    parts: list[str] = []
    for segment in message:
        segment_type = _segment_type(segment)
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
        elif segment_type == "video":
            label = _first_value(data, ("file", "url", "summary"))
            parts.append(f"[video: {label}]" if label else "[video]")
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


def extract_image_urls(message: Iterable[Any]) -> list[str]:
    return extract_media_urls(message).image_urls


def extract_media_urls(message: Iterable[Any]) -> MediaUrls:
    image_urls: list[str] = []
    video_urls: list[str] = []
    markers: list[str] = []
    for segment in message:
        segment_type = _segment_type(segment)
        if segment_type not in {"image", "video"}:
            continue
        data = _data(segment)
        label = _first_value(data, ("url", "file"))
        if not _is_http_url(label):
            continue
        marker_label = _first_value(data, ("file", "url", "summary"))
        if marker_label:
            marker_type = "image" if segment_type == "image" else "video"
            markers.append(f"[{marker_type}: {marker_label}]")
        if segment_type == "video" or (
            segment_type == "image" and _is_dynamic_media_url(label)
        ):
            video_urls.append(label)
        elif segment_type == "image":
            image_urls.append(label)
    return MediaUrls(image_urls=image_urls, video_urls=video_urls, markers=markers)


def extract_repeat_media(message: Iterable[Any]) -> RepeatMedia:
    for segment in message:
        if _segment_type(segment) != "face":
            continue
        face_id = _first_value(_data(segment), ("id",))
        if face_id:
            return RepeatMedia(kind="face", face_id=face_id)
    for segment in message:
        if _segment_type(segment) != "image":
            continue
        data = _data(segment)
        file_value = _first_value(data, ("file",))
        url_value = _first_value(data, ("url",))
        if file_value or url_value:
            return RepeatMedia(kind="image", file=file_value, url=url_value)
    return RepeatMedia()


def is_reply_to(message: Iterable[Any]) -> bool:
    return any(_segment_type(segment) == "reply" for segment in message)


def extract_reply_message_id(message: Iterable[Any]) -> str:
    for segment in message:
        if _segment_type(segment) != "reply":
            continue
        return _first_value(_data(segment), ("id", "message_id"))
    return ""
