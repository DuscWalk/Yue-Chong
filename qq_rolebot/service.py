from __future__ import annotations

from typing import Protocol

from qq_rolebot.admin import handle_admin_command, is_admin_command
from qq_rolebot.config import Settings
from qq_rolebot.guardrails import clean_response
from qq_rolebot.model_client import ModelResult
from qq_rolebot.persona import load_persona
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter, decide_trigger
from qq_rolebot.prompting import build_chat_messages
from qq_rolebot.storage import MessageRecord, Storage


class ChatModel(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> ModelResult:
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
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.model = model
        self.rate_limiter = rate_limiter
        self.tool_runner = tool_runner
        self.followup_tracker = followup_tracker
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
        if message.is_private:
            return await self._handle_private(message)

        if message.group_id not in self.settings.group_whitelist:
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
                return self._switch_persona(parts[2].lower())
            return await handle_admin_command(
                message.text,
                sender_id=message.user_id,
                group_id=message.group_id,
                now=message.created_at,
                settings=self.settings,
                storage=self.storage,
            )

        group = await self.storage.get_group_settings(message.group_id)
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
        if not decision.should_reply:
            return None

        tool_context = ""
        if self.tool_runner is not None:
            tool_result = await self.tool_runner.run(message)
            if getattr(tool_result, "direct_reply", None):
                reply = clean_response(
                    tool_result.direct_reply,
                    max_chars=self.settings.max_output_chars,
                    sensitive_words=self.settings.sensitive_words,
                )
                return reply
            tool_context = str(getattr(tool_result, "context", "") or "")

        context = await self.storage.recent_messages(message.group_id)
        result = await self.model.chat(
            build_chat_messages(self.persona, context, message, tool_context=tool_context)
        )
        if not result.ok:
            return None

        reply = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            return None

        return reply

    async def _handle_private(self, message: IncomingMessage) -> str | None:
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
                reply = clean_response(
                    tool_result.direct_reply,
                    max_chars=self.settings.max_output_chars,
                    sensitive_words=self.settings.sensitive_words,
                )
                return reply
            tool_context = str(getattr(tool_result, "context", "") or "")

        context = await self.storage.recent_messages(context_id)
        result = await self.model.chat(
            build_chat_messages(self.persona, context, message, tool_context=tool_context)
        )
        if not result.ok:
            return None

        reply = clean_response(
            result.text,
            max_chars=self.settings.max_output_chars,
            sensitive_words=self.settings.sensitive_words,
        )
        if reply is None:
            return None

        return reply
