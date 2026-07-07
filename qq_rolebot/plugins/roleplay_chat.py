from __future__ import annotations

import random
import time

from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment

from qq_rolebot.config import load_settings
from qq_rolebot.message_segments import is_reply_to, summarize_segments
from qq_rolebot.model_client import ModelClient
from qq_rolebot.persona import load_persona
from qq_rolebot.persona_sources import PersonaSourceClient
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter
from qq_rolebot.service import ChatService
from qq_rolebot.storage import Storage
from qq_rolebot.tavily import TavilyClient
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolRouter
from qq_rolebot.tool_runner import ToolRunner
from qq_rolebot.tts_client import TTSClient
from qq_rolebot.voice_policy import VoicePolicy
from qq_rolebot.voice_service import VoiceService

settings = load_settings()
storage = Storage(
    settings.database_path,
    context_limit=20,
    default_probability=settings.default_random_reply_probability,
)
model = ModelClient(
    api_base=settings.model_api_base,
    api_key=settings.model_api_key,
    model_name=settings.model_name,
    timeout_seconds=settings.model_timeout_seconds,
)
persona = load_persona(settings.persona_path)
search_client = None
if settings.tavily_api_key:
    search_client = TavilyClient(
        api_key=settings.tavily_api_key,
        api_base=settings.tavily_api_base,
        timeout_seconds=settings.search_timeout_seconds,
    )

persona_source_client = PersonaSourceClient(
    sources=persona.sources,
    timeout_seconds=settings.search_timeout_seconds,
)
tool_runner = ToolRunner(
    router=ToolRouter(
        search_cooldown_seconds=settings.search_cooldown_seconds,
        persona_names=[persona.name, "Chongyue", "\u91cd\u5cb3"],
    ),
    time_tool=TimeTool(timezone="Asia/Shanghai"),
    search_client=search_client,
    persona_source_client=persona_source_client,
    search_max_results=settings.search_max_results,
    enable_time=settings.tools_enable_time,
    enable_search=settings.tools_enable_search and search_client is not None,
    enable_persona_sources=settings.tools_enable_persona_sources,
)
service = ChatService(
    settings=settings,
    storage=storage,
    model=model,
    rate_limiter=RateLimiter(),
    tool_runner=tool_runner,
    followup_tracker=FollowupTracker(
        window_seconds=settings.followup_window_seconds,
        trigger_keywords=settings.followup_trigger_keywords,
    ),
)
voice_service = None
if settings.tts_enabled and settings.tts_api_url:
    voice_service = VoiceService(
        enabled=True,
        policy=VoicePolicy(
            trigger_keywords=settings.tts_trigger_keywords,
            cooldown_seconds=settings.tts_cooldown_seconds,
        ),
        client=TTSClient(
            api_url=settings.tts_api_url,
            timeout_seconds=settings.tts_timeout_seconds,
            backend=settings.tts_backend,
            ref_audio_path=str(settings.tts_ref_audio_path or ""),
            prompt_text=settings.tts_prompt_text,
            prompt_lang=settings.tts_prompt_lang,
            text_lang=settings.tts_text_lang,
            api_key=settings.tts_api_key,
            model=settings.tts_model,
            audio_format=settings.tts_audio_format,
        ),
        cache_dir=settings.tts_cache_dir,
        max_chars=settings.tts_max_chars,
        speaker=settings.tts_speaker,
        style=settings.tts_style,
        dialect_hint=settings.tts_dialect_hint,
    )

matcher = on_message(priority=50, block=False)


async def init_storage() -> None:
    await storage.init()


try:
    driver = get_driver()
except ValueError:
    driver = None

if driver is not None:
    driver.on_startup(init_storage)


def extract_message_text(event: MessageEvent) -> str:
    message = getattr(event, "message", None)
    if message is None:
        return event.get_plaintext().strip()
    text = summarize_segments(message).strip()
    return text or event.get_plaintext().strip()


def is_at_bot(event: GroupMessageEvent, bot_id: int) -> bool:
    if bool(getattr(event, "to_me", False)):
        return True
    for segment in event.message:
        if segment.type == "at" and str(segment.data.get("qq")) == str(bot_id):
            return True
    return False


def is_reply_to_bot(event: MessageEvent, bot_id: int) -> bool:
    reply = getattr(event, "reply", None)
    sender = getattr(reply, "sender", None)
    sender_id = getattr(sender, "user_id", None)
    if sender_id is not None:
        return str(sender_id) == str(bot_id)
    return bool(getattr(event, "to_me", False)) and is_reply_to(getattr(event, "message", []))


def build_incoming_message(event: MessageEvent, bot_id: int) -> IncomingMessage | None:
    text = extract_message_text(event)
    if not text:
        return None

    sender = event.sender
    nickname = getattr(sender, "card", "") or getattr(sender, "nickname", "") or str(event.user_id)
    message_type = getattr(event, "message_type", "")
    if message_type == "private":
        return IncomingMessage(
            group_id=0,
            user_id=int(event.user_id),
            nickname=nickname,
            text=text,
            is_at_bot=False,
            is_private=True,
            is_reply_to_bot=False,
            created_at=int(getattr(event, "time", int(time.time()))),
        )

    if message_type == "group":
        return IncomingMessage(
            group_id=int(event.group_id),
            user_id=int(event.user_id),
            nickname=nickname,
            text=text,
            is_at_bot=is_at_bot(event, bot_id),
            is_reply_to_bot=is_reply_to_bot(event, bot_id),
            created_at=int(getattr(event, "time", int(time.time()))),
        )

    return None


@matcher.handle()
async def handle_message(bot: Bot, event: MessageEvent) -> None:
    incoming = build_incoming_message(event, settings.bot_qq)
    if incoming is None:
        return

    reply = await service.handle(incoming, random_value=random.randrange(100))
    if reply:
        if voice_service is not None:
            voice = await voice_service.maybe_render(incoming, reply=reply)
            if voice.file_path is not None:
                await bot.send(event, MessageSegment.record(str(voice.file_path)))
                return
        await bot.send(event, MessageSegment.text(reply))
