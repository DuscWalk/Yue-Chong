from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OutgoingKind = Literal["text", "image", "face", "record"]


@dataclass(frozen=True)
class OutgoingMessage:
    kind: OutgoingKind
    text: str = ""
    file: str = ""
    url: str = ""
    face_id: str = ""
    source: str = ""

    @property
    def is_empty(self) -> bool:
        if self.kind == "text":
            return not self.text.strip()
        if self.kind in {"image", "record"}:
            return not (self.file.strip() or self.url.strip())
        if self.kind == "face":
            return not self.face_id.strip()
        return True


class _TextAccessor:
    def __get__(self, instance: "OutgoingReply | None", owner: "type[OutgoingReply]"):
        if instance is None:
            return lambda text, *, source: owner(
                source=source,
                messages=[OutgoingMessage(kind="text", text=text, source=source)],
            )
        return "\n".join(
            message.text.strip()
            for message in instance.messages
            if message.kind == "text" and message.text.strip()
        )


@dataclass(frozen=True)
class OutgoingReply:
    source: str
    messages: list[OutgoingMessage] = field(default_factory=list)

    text = _TextAccessor()

    @property
    def is_empty(self) -> bool:
        return not [message for message in self.messages if not message.is_empty]

    def with_message(self, message: OutgoingMessage) -> "OutgoingReply":
        return OutgoingReply(source=self.source, messages=[*self.messages, message])
