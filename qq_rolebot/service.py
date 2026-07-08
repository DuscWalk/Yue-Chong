from __future__ import annotations

import time
from typing import Protocol

from qq_rolebot.admin import handle_admin_command, is_admin_command
from qq_rolebot.config import Settings
from qq_rolebot.debug_trace import DebugTrace, DebugTraceLogger
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter, decide_trigger
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.storage import MessageRecord, Storage

REPEAT_REPLY_COOLDOWN_SECONDS = 600
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
        self._repeat_reply_cooldowns: dict[tuple[int, str], int] = {}
        self.persona = load_persona(settings.persona_path)

    def _switch_persona(self, variant: str) -> str:
        if variant == "dialect":
            self.persona = load_persona(self.settings.persona_path.parent / "default_dialect.yaml")
            return "persona switched to dialect"
        if variant == "standard":
            self.persona = load_persona(self.settings.persona_path.parent / "default.yaml")
            return "persona switched to standard"
        return "usage: /bot persona dialect|standard"

    async def handle(self, message: IncomingMessage, *, random_value: int) -> str | None:
        trace = self._start_trace(message)
        if message.is_private:
            return await self._handle_private(message, trace=trace)

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
                self._trace(trace, "reply.final", {"reply": reply, "source": "admin"})
                return reply
            reply = await handle_admin_command(
                message.text,
                sender_id=message.user_id,
                group_id=message.group_id,
                now=message.created_at,
                settings=self.settings,
                storage=self.storage,
            )
            self._trace(trace, "reply.final", {"reply": reply, "source": "admin"})
            return reply

        group = await self.storage.get_group_settings(message.group_id)
        repeat_reply = await self._repeat_reply(message, muted_until=group.muted_until)
        if repeat_reply is not None and group.enabled:
            self._trace(trace, "reply.final", {"reply": repeat_reply, "source": "repeat"})
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
                self._trace(trace, "reply.final", {"reply": reply, "source": "tool"})
                return reply
            tool_context = str(getattr(tool_result, "context", "") or "")
            self._trace(trace, "tool.result", {"direct_reply": None, "context": tool_context})

        tool_context = self._join_context(
            tool_context,
            await self._vision_context(message, trace=trace),
        )
        context = await self.storage.recent_messages(message.group_id)
        messages = build_chat_messages(self.persona, context, message, tool_context=tool_context)
        self._trace(trace, "model.prompt", {"messages": messages})
        started = time.monotonic()
        result = await self.model.chat(messages)
        self._trace(
            trace,
            "model.response",
            {
                "ok": result.ok,
                "text": result.text,
                "error": result.error,
                "elapsed_ms": self._elapsed_ms(started),
            },
        )
        if not result.ok:
            self._trace(trace, "reply.final", {"reply": None, "source": "model_error"})
            return None

        reply = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            self._trace(trace, "reply.final", {"reply": None, "source": "guardrails"})
            return None

        self._trace(trace, "reply.final", {"reply": reply, "source": "model"})
        return reply

    async def _vision_context(self, message: IncomingMessage, *, trace: DebugTrace | None) -> str:
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
        context = f"Vision Context:\n{summary}"
        self._trace(trace, "vision.context", {"context": context})
        return context

    @staticmethod
    def _join_context(*items: str) -> str:
        return "\n\n".join(item for item in items if item)

    async def _repeat_reply(self, message: IncomingMessage, *, muted_until: int) -> str | None:
        if not self.settings.repeat_reply_enabled:
            return None
        if muted_until > message.created_at:
            return None
        if message.is_at_bot or message.is_reply_to_bot:
            return None

        context = await self.storage.recent_messages(message.group_id)
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
                self._trace(trace, "reply.final", {"reply": reply, "source": "tool"})
                return reply
            tool_context = str(getattr(tool_result, "context", "") or "")
            self._trace(trace, "tool.result", {"direct_reply": None, "context": tool_context})

        tool_context = self._join_context(
            tool_context,
            await self._vision_context(message, trace=trace),
        )
        context = await self.storage.recent_messages(context_id)
        messages = build_chat_messages(self.persona, context, message, tool_context=tool_context)
        self._trace(trace, "model.prompt", {"messages": messages})
        started = time.monotonic()
        result = await self.model.chat(messages)
        self._trace(
            trace,
            "model.response",
            {
                "ok": result.ok,
                "text": result.text,
                "error": result.error,
                "elapsed_ms": self._elapsed_ms(started),
            },
        )
        if not result.ok:
            self._trace(trace, "reply.final", {"reply": None, "source": "model_error"})
            return None

        reply = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            self._trace(trace, "reply.final", {"reply": None, "source": "guardrails"})
            return None

        self._trace(trace, "reply.final", {"reply": reply, "source": "model"})
        return reply

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
            }
        )

    @staticmethod
    def _trace(trace: DebugTrace | None, name: str, data: dict) -> None:
        if trace is not None:
            trace.event(name, data)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
