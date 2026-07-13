from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
from qq_rolebot.policy import IncomingMessage


@dataclass(frozen=True)
class RepeatEntry:
    group_id: int
    user_id: int
    signature: str
    text: str
    created_at: int
    media_kind: str = ""
    media_file: str = ""
    media_url: str = ""
    media_face_id: str = ""
    media_emoji_id: str = ""
    media_emoji_package_id: str = ""
    media_key: str = ""
    media_summary: str = ""
    media_image_sub_type: int | None = None


class RepeatTracker:
    def __init__(
        self,
        *,
        threshold: int,
        cooldown_seconds: int = 600,
        window_seconds: int = 600,
    ) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.window_seconds = window_seconds
        self._entries: dict[int, deque[RepeatEntry]] = defaultdict(deque)
        self._cooldowns: dict[tuple[int, str], int] = {}

    def record_and_match(self, message: IncomingMessage, *, now: int) -> OutgoingReply | None:
        entry = self._entry(message)
        if entry is None:
            return None
        entries = self._entries[message.group_id]
        entries.append(entry)
        self._prune(message.group_id, now=now)
        if len(entries) < self.threshold:
            return None
        tail = list(entries)[-self.threshold :]
        if any(item.signature != entry.signature for item in tail):
            return None
        if len({item.user_id for item in tail}) < 2:
            return None
        cooldown_key = (message.group_id, entry.signature)
        last_reply_at = self._cooldowns.get(cooldown_key)
        if last_reply_at is not None and now - last_reply_at < self.cooldown_seconds:
            return None
        reply = self._reply(entry)
        if reply is None:
            return None
        self._cooldowns[cooldown_key] = now
        return reply

    def _entry(self, message: IncomingMessage) -> RepeatEntry | None:
        signature = message.repeat_signature.strip() or self._text_signature(message.text)
        if not signature:
            return None
        return RepeatEntry(
            group_id=message.group_id,
            user_id=message.user_id,
            signature=signature,
            text=message.text.strip(),
            created_at=message.created_at,
            media_kind=message.repeat_media_kind,
            media_file=message.repeat_media_file,
            media_url=message.repeat_media_url,
            media_face_id=message.repeat_media_face_id,
            media_emoji_id=message.repeat_media_emoji_id,
            media_emoji_package_id=message.repeat_media_emoji_package_id,
            media_key=message.repeat_media_key,
            media_summary=message.repeat_media_summary,
            media_image_sub_type=message.repeat_media_image_sub_type,
        )

    @staticmethod
    def _text_signature(text: str) -> str:
        compact = text.strip()
        return f"text:{compact}" if compact else ""

    @staticmethod
    def _reply(entry: RepeatEntry) -> OutgoingReply | None:
        if entry.media_kind == "image":
            if entry.media_image_sub_type is None:
                return None
            value = entry.media_file or entry.media_url
            if value:
                return OutgoingReply(
                    source="repeat",
                    messages=[
                        OutgoingMessage(
                            kind="image",
                            file=value,
                            image_sub_type=entry.media_image_sub_type,
                            summary=entry.media_summary,
                            source="repeat",
                        )
                    ],
                )
        if entry.media_kind == "face" and entry.media_face_id:
            return OutgoingReply(
                source="repeat",
                messages=[
                    OutgoingMessage(kind="face", face_id=entry.media_face_id, source="repeat")
                ],
            )
        if entry.media_kind == "mface":
            if entry.media_emoji_id and entry.media_emoji_package_id and entry.media_key:
                return OutgoingReply(
                    source="repeat",
                    messages=[
                        OutgoingMessage(
                            kind="mface",
                            emoji_id=entry.media_emoji_id,
                            emoji_package_id=entry.media_emoji_package_id,
                            key=entry.media_key,
                            summary=entry.media_summary or "[商城表情]",
                            source="repeat",
                        )
                    ],
                )
            return None
        if entry.text:
            return OutgoingReply.text(entry.text, source="repeat")
        return None

    def _prune(self, group_id: int, *, now: int) -> None:
        entries = self._entries[group_id]
        while entries and now - entries[0].created_at > self.window_seconds:
            entries.popleft()
