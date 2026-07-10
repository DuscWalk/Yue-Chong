from __future__ import annotations

import re
import time
from typing import Protocol

from qq_rolebot.admin import handle_admin_command, is_admin_command
from qq_rolebot.agent_runner import AgentRunner
from qq_rolebot.config import Settings
from qq_rolebot.debug_trace import DebugTrace, DebugTraceLogger
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.outgoing import OutgoingReply
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter, decide_trigger
from qq_rolebot.repeat_policy import RepeatTracker
from qq_rolebot.storage import MessageRecord, Storage, VisionContextRecord

REPEAT_REPLY_COOLDOWN_SECONDS = 600
MEDIA_MARKER_PATTERN = re.compile(r"\[(?:image|video): [^\]]+\]")
VISUAL_FOLLOWUP_HINTS = (
    "这",
    "这个",
    "那",
    "图",
    "图片",
    "表情",
    "谁",
    "啥",
    "什么",
    "什么意思",
    "哪",
    "画",
)
VISION_FAILURE_CONTEXT = (
    "Vision Context:\n"
    "视觉识别失败：{error}。这条消息包含图片、表情包、动图或视频，"
    "但当前没有可靠视觉内容；不要猜测图片内容、角色身份、文字或来源。"
    "如果用户询问图片是谁或是什么，应说明暂时看不清或识别超时。"
)


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
        ...


class VisionClientProtocol(Protocol):
    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
        trace: DebugTrace | None = None,
    ):
        ...


class ToolRunnerProtocol(Protocol):
    async def run(self, message: IncomingMessage):
        ...


class ChatService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        model: ChatModel,
        rate_limiter: RateLimiter,
        tool_runner: ToolRunnerProtocol | None = None,
        followup_tracker: FollowupTracker | None = None,
        vision_client: VisionClientProtocol | None = None,
        trace_logger: DebugTraceLogger | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model = model
        self.rate_limiter = rate_limiter
        self.tool_runner = tool_runner
        self.followup_tracker = followup_tracker
        self.vision_client = vision_client
        self.trace_logger = trace_logger
        self.agent_runner = AgentRunner(settings=settings, model=model)
        self.repeat_tracker = RepeatTracker(
            threshold=settings.repeat_reply_threshold,
            cooldown_seconds=REPEAT_REPLY_COOLDOWN_SECONDS,
            window_seconds=settings.context_window_seconds,
        )
        self.reply_enhancer = None
        self.persona = load_persona(settings.persona_path)

    def _switch_persona(self, variant: str) -> str:
        if variant == "dialect":
            self.persona = load_persona(self.settings.persona_path.parent / "default_dialect.yaml")
            return "persona switched to dialect"
        if variant == "standard":
            self.persona = load_persona(self.settings.persona_path.parent / "default.yaml")
            return "persona switched to standard"
        return "usage: /bot persona dialect|standard"

    async def _save_bot_reply(self, *, group_id: int, reply: str, created_at: int) -> None:
        await self.storage.save_message(
            MessageRecord(
                group_id=group_id,
                user_id=self.settings.bot_qq,
                nickname=self.persona.name,
                text=reply,
                created_at=created_at,
            )
        )

    async def handle(self, message: IncomingMessage, *, random_value: int) -> str | None:
        reply = await self.handle_reply(message, random_value=random_value)
        return reply.text if reply is not None else None

    async def handle_reply(
        self,
        message: IncomingMessage,
        *,
        random_value: int,
    ) -> OutgoingReply | None:
        trace = self._start_trace(message)
        if message.is_private:
            return await self._handle_private_reply(message, trace=trace, random_value=random_value)

        if message.group_id not in self.settings.group_whitelist:
            self._trace(trace, "message.ignored", {"reason": "group not whitelisted"})
            return None

        await self.storage.save_message(
            MessageRecord(
                group_id=message.group_id,
                user_id=message.user_id,
                nickname=message.nickname,
                text=message.text,
                created_at=message.created_at,
            )
        )

        if is_admin_command(message.text):
            parts = message.text.strip().split()
            if (
                len(parts) == 3
                and parts[0] == "/bot"
                and parts[1].lower() == "persona"
                and message.user_id in self.settings.admin_users
            ):
                reply = self._switch_persona(parts[2].lower())
                await self._save_bot_reply(
                    group_id=message.group_id,
                    reply=reply,
                    created_at=message.created_at,
                )
                self._trace(trace, "reply.final", {"reply": reply, "source": "admin"})
                return OutgoingReply.text(reply, source="admin")
            reply = await handle_admin_command(
                message.text,
                sender_id=message.user_id,
                group_id=message.group_id,
                now=message.created_at,
                settings=self.settings,
                storage=self.storage,
            )
            await self._save_bot_reply(
                group_id=message.group_id,
                reply=reply,
                created_at=message.created_at,
            )
            self._trace(trace, "reply.final", {"reply": reply, "source": "admin"})
            return OutgoingReply.text(reply, source="admin")

        group = await self.storage.get_group_settings(message.group_id)
        if self.settings.repeat_reply_enabled and group.enabled:
            if group.muted_until <= message.created_at and not (
                message.is_at_bot or message.is_reply_to_bot
            ):
                repeat_reply = self.repeat_tracker.record_and_match(
                    message,
                    now=message.created_at,
                )
                if repeat_reply is not None:
                    repeat_text = repeat_reply.text or message.text
                    await self._save_bot_reply(
                        group_id=message.group_id,
                        reply=repeat_text,
                        created_at=message.created_at,
                    )
                    self._trace(
                        trace,
                        "reply.final",
                        {"reply": repeat_text, "source": "repeat"},
                    )
                    return repeat_reply

        followup_matched = False
        if self.followup_tracker is not None:
            if message.is_at_bot or message.is_reply_to_bot:
                self.followup_tracker.record(message, now=message.created_at)
            else:
                followup_matched = self.followup_tracker.should_trigger(
                    message,
                    now=message.created_at,
                )

        decision = decide_trigger(
            message,
            group_enabled=group.enabled,
            muted_until=group.muted_until,
            keywords=self.settings.keywords,
            random_probability=group.random_probability,
            now=message.created_at,
            random_value=random_value,
            followup_matched=followup_matched,
        )
        self._trace(
            trace,
            "trigger.decision",
            {
                "should_reply": decision.should_reply,
                "kind": decision.kind.value,
                "reason": decision.reason,
            },
        )
        if not decision.should_reply:
            self._trace(trace, "message.ignored", {"reason": decision.reason})
            return None

        tool_context = ""
        if self.tool_runner is not None:
            tool_result = await self.tool_runner.run(message)
            if getattr(tool_result, "direct_reply", None):
                self._trace(
                    trace,
                    "tool.result",
                    {
                        "direct_reply": tool_result.direct_reply,
                        "context": str(getattr(tool_result, "context", "") or ""),
                    },
                )
                reply = clean_response(
                    tool_result.direct_reply,
                    max_chars=self.settings.max_output_chars,
                    sensitive_words=self.settings.sensitive_words,
                )
                if reply is not None:
                    await self._save_bot_reply(
                        group_id=message.group_id,
                        reply=reply,
                        created_at=message.created_at,
                    )
                self._trace(trace, "reply.final", {"reply": reply, "source": "tool"})
                return OutgoingReply.text(reply, source="tool") if reply is not None else None
            tool_context = str(getattr(tool_result, "context", "") or "")
            self._trace(trace, "tool.result", {"direct_reply": None, "context": tool_context})

        tool_context = self._join_context(
            tool_context,
            await self._vision_context(message, context_id=message.group_id, trace=trace),
        )
        context = await self.storage.recent_messages(message.group_id, now=message.created_at)
        agent_result = await self.agent_runner.run(
            persona=self.persona,
            context=context,
            message=message,
            tool_context=tool_context,
        )
        self._trace(trace, "model.prompt", {"messages": agent_result.messages or []})
        self._trace(
            trace,
            "model.response",
            {
                "ok": agent_result.ok,
                "text": agent_result.model_text,
                "error": agent_result.error,
                "elapsed_ms": agent_result.elapsed_ms,
            },
        )
        if not agent_result.ok:
            self._trace(trace, "reply.final", {"reply": None, "source": "model_error"})
            return None

        reply = agent_result.text

        await self._save_bot_reply(
            group_id=message.group_id,
            reply=reply,
            created_at=message.created_at,
        )
        self._trace(trace, "reply.final", {"reply": reply, "source": "model"})
        return OutgoingReply.text(reply, source="model")

    async def _vision_context(
        self,
        message: IncomingMessage,
        *,
        context_id: int,
        trace: DebugTrace | None,
    ) -> str:
        reusable = await self._stored_vision_context(message, context_id=context_id)
        if reusable is not None:
            context = self._format_vision_context(
                reusable.summary,
                media_marker=reusable.media_marker,
            )
            self._trace(
                trace,
                "vision.context",
                {
                    "context": context,
                    "source": "stored",
                    "media_marker": reusable.media_marker,
                },
            )
            return context
        if self.vision_client is None or not (message.image_urls or message.video_urls):
            self._trace(
                trace,
                "vision.context",
                {"context": "", "reason": "no vision client or media"},
            )
            return ""
        result = await self.vision_client.describe(
            message.image_urls,
            video_urls=message.video_urls,
            trace=trace,
        )
        if not getattr(result, "ok", False):
            error = str(getattr(result, "error", "") or "unknown vision error")
            context = VISION_FAILURE_CONTEXT.format(error=error)
            self._trace(
                trace,
                "vision.context",
                {"context": context, "error": error},
            )
            return context
        summary = str(getattr(result, "summary", "") or "").strip()
        if not summary:
            self._trace(trace, "vision.context", {"context": "", "reason": "empty summary"})
            return ""
        await self._save_vision_context(
            context_id=context_id,
            message=message,
            summary=summary,
            trace=trace,
        )
        media_marker = self._media_markers(message)[0] if self._media_markers(message) else ""
        context = self._format_vision_context(summary, media_marker=media_marker)
        self._trace(trace, "vision.context", {"context": context})
        return context

    @staticmethod
    def _join_context(*items: str) -> str:
        return "\n\n".join(item for item in items if item)

    async def _stored_vision_context(
        self,
        message: IncomingMessage,
        *,
        context_id: int,
    ) -> VisionContextRecord | None:
        media_markers = self._media_markers(message)
        if media_markers:
            return await self.storage.find_vision_context(
                context_id,
                media_markers=media_markers,
                now=message.created_at,
            )
        if message.image_urls or message.video_urls:
            return None
        if not self._looks_like_visual_followup(message.text):
            return None
        return await self.storage.find_vision_context(
            context_id,
            media_markers=[],
            now=message.created_at,
        )

    async def _save_vision_context(
        self,
        *,
        context_id: int,
        message: IncomingMessage,
        summary: str,
        trace: DebugTrace | None,
    ) -> None:
        media_markers = self._media_markers(message)
        for media_marker in media_markers:
            await self.storage.save_vision_context(
                VisionContextRecord(
                    group_id=context_id,
                    media_marker=media_marker,
                    summary=summary,
                    created_at=message.created_at,
                )
            )
        if media_markers:
            self._trace(
                trace,
                "vision.context.saved",
                {"media_markers": media_markers, "count": len(media_markers)},
            )

    @staticmethod
    def _media_markers(message: IncomingMessage) -> list[str]:
        markers = [marker.strip() for marker in message.media_markers if marker.strip()]
        markers.extend(MEDIA_MARKER_PATTERN.findall(message.text))
        return list(dict.fromkeys(markers))

    @staticmethod
    def _looks_like_visual_followup(text: str) -> bool:
        compact = "".join(text.split())
        if not compact or len(compact) > 30:
            return False
        return any(hint in compact for hint in VISUAL_FOLLOWUP_HINTS)

    @staticmethod
    def _format_vision_context(summary: str, *, media_marker: str = "") -> str:
        lines = [
            "Vision Context:",
            (
                "这是当前图片或追问所对应的视觉摘要；"
                "若它与 Recent chat context 里的旧回复冲突，优先参考这里。"
            ),
        ]
        if media_marker:
            lines.append(f"关联图片：{media_marker}")
        lines.append(summary)
        return "\n".join(lines)

    async def _repeat_reply(self, message: IncomingMessage, *, muted_until: int) -> str | None:
        if not self.settings.repeat_reply_enabled:
            return None
        if muted_until > message.created_at:
            return None
        if message.is_at_bot or message.is_reply_to_bot:
            return None

        context = await self.storage.recent_messages(message.group_id, now=message.created_at)
        context = [item for item in context if item.user_id != self.settings.bot_qq]
        threshold = self.settings.repeat_reply_threshold
        if len(context) < threshold:
            return None

        tail = context[-threshold:]
        text = message.text.strip()
        if not text:
            return None
        if any(item.text.strip() != text for item in tail):
            return None
        if len({item.user_id for item in tail}) < 2:
            return None

        cooldown_key = (message.group_id, text)
        last_reply_at = self._repeat_reply_cooldowns.get(cooldown_key)
        if (
            last_reply_at is not None
            and message.created_at - last_reply_at < REPEAT_REPLY_COOLDOWN_SECONDS
        ):
            return None

        reply = clean_response(
            text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            return None

        self._repeat_reply_cooldowns[cooldown_key] = message.created_at
        return reply

    async def _handle_private(
        self,
        message: IncomingMessage,
        *,
        trace: DebugTrace | None,
    ) -> str | None:
        reply = await self._handle_private_reply(message, trace=trace, random_value=100)
        return reply.text if reply is not None else None

    async def _handle_private_reply(
        self,
        message: IncomingMessage,
        *,
        trace: DebugTrace | None,
        random_value: int,
    ) -> OutgoingReply | None:
        context_id = -abs(message.user_id)
        await self.storage.save_message(
            MessageRecord(
                group_id=context_id,
                user_id=message.user_id,
                nickname=message.nickname,
                text=message.text,
                created_at=message.created_at,
            )
        )

        tool_context = ""
        if self.tool_runner is not None:
            tool_result = await self.tool_runner.run(message)
            if getattr(tool_result, "direct_reply", None):
                self._trace(
                    trace,
                    "tool.result",
                    {
                        "direct_reply": tool_result.direct_reply,
                        "context": str(getattr(tool_result, "context", "") or ""),
                    },
                )
                reply = clean_response(
                    tool_result.direct_reply,
                    max_chars=self.settings.max_output_chars,
                    sensitive_words=self.settings.sensitive_words,
                )
                if reply is not None:
                    await self._save_bot_reply(
                        group_id=context_id,
                        reply=reply,
                        created_at=message.created_at,
                    )
                self._trace(trace, "reply.final", {"reply": reply, "source": "tool"})
                return OutgoingReply.text(reply, source="tool") if reply is not None else None
            tool_context = str(getattr(tool_result, "context", "") or "")
            self._trace(trace, "tool.result", {"direct_reply": None, "context": tool_context})

        tool_context = self._join_context(
            tool_context,
            await self._vision_context(message, context_id=context_id, trace=trace),
        )
        context = await self.storage.recent_messages(context_id, now=message.created_at)
        agent_result = await self.agent_runner.run(
            persona=self.persona,
            context=context,
            message=message,
            tool_context=tool_context,
        )
        self._trace(trace, "model.prompt", {"messages": agent_result.messages or []})
        self._trace(
            trace,
            "model.response",
            {
                "ok": agent_result.ok,
                "text": agent_result.model_text,
                "error": agent_result.error,
                "elapsed_ms": agent_result.elapsed_ms,
            },
        )
        if not agent_result.ok:
            self._trace(trace, "reply.final", {"reply": None, "source": "model_error"})
            return None

        reply = agent_result.text

        await self._save_bot_reply(group_id=context_id, reply=reply, created_at=message.created_at)
        self._trace(trace, "reply.final", {"reply": reply, "source": "model"})
        return OutgoingReply.text(reply, source="model")

    def _start_trace(self, message: IncomingMessage) -> DebugTrace | None:
        if self.trace_logger is None:
            return None
        return self.trace_logger.start_trace(
            {
                "group_id": message.group_id,
                "user_id": message.user_id,
                "nickname": message.nickname,
                "text": message.text,
                "is_private": message.is_private,
                "is_at_bot": message.is_at_bot,
                "is_reply_to_bot": message.is_reply_to_bot,
                "created_at": message.created_at,
                "image_urls": message.image_urls,
                "video_urls": message.video_urls,
                "media_markers": message.media_markers,
                "media_source": message.media_source,
                "reply_message_id": message.reply_message_id,
            }
        )

    @staticmethod
    def _trace(trace: DebugTrace | None, name: str, data: dict) -> None:
        if trace is not None:
            trace.event(name, data)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
