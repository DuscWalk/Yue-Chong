from __future__ import annotations

from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
from qq_rolebot.stickers import StickerLibrary


class ReplyEnhancer:
    def __init__(
        self,
        *,
        enabled: bool,
        probability: int,
        library: StickerLibrary | None,
    ) -> None:
        self.enabled = enabled
        self.probability = probability
        self.library = library

    def enhance(self, reply: OutgoingReply, *, random_value: int) -> OutgoingReply:
        if not self.enabled or self.library is None:
            return reply
        if reply.is_empty or not reply.text.strip():
            return reply
        if self.probability <= 0 or random_value >= self.probability:
            return reply
        item = self.library.select(tags=["reply"], random_value=random_value)
        if item is None:
            return reply
        if item.is_sendable_mface:
            return reply.with_message(
                OutgoingMessage(
                    kind="mface",
                    emoji_id=item.emoji_id,
                    emoji_package_id=item.emoji_package_id,
                    key=item.key,
                    summary=item.summary,
                    file=str(item.path),
                    source="sticker",
                )
            )
        return reply.with_message(
            OutgoingMessage(
                kind="image",
                file=str(item.path),
                image_sub_type=1,
                summary=item.summary or "[动画表情]",
                source="sticker",
            )
        )
