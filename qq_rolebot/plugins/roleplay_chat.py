from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment

from qq_rolebot.config import load_settings
from qq_rolebot.custom_faces import CustomFaceRegistrar
from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.image_preprocessor import ImagePreprocessor
from qq_rolebot.message_segments import (
    MediaUrls,
    extract_media_urls,
    extract_repeat_media,
    extract_reply_message_id,
    is_reply_to,
    summarize_segments,
)
from qq_rolebot.model_client import ModelClient
from qq_rolebot.outgoing import OutgoingMessage, OutgoingReply
from qq_rolebot.persona import load_persona
from qq_rolebot.persona_sources import PersonaSourceClient
from qq_rolebot.policy import FollowupTracker, IncomingMessage, RateLimiter
from qq_rolebot.reply_enhancer import ReplyEnhancer
from qq_rolebot.serpapi_client import SerpApiLensClient, SerpApiWebClient
from qq_rolebot.service import ChatService
from qq_rolebot.stickers import StickerLibrary
from qq_rolebot.storage import Storage
from qq_rolebot.tavily import TavilyClient
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolRouter
from qq_rolebot.tool_runner import ToolRunner
from qq_rolebot.tts_client import TTSClient
from qq_rolebot.vision_cache import VisionCache
from qq_rolebot.vision_client import VisualAnalyzer
from qq_rolebot.vision_pipeline import VisionPipeline
from qq_rolebot.voice_policy import VoicePolicy
from qq_rolebot.voice_service import VoiceService

settings = load_settings()


def vision_settings_complete(candidate_settings) -> bool:
    return all(
        (
            candidate_settings.vision_model_api_base,
            candidate_settings.vision_model_api_key,
            candidate_settings.vision_model_name,
        )
    )


def build_vision_pipeline(candidate_settings):
    if not candidate_settings.vision_model_enabled or not vision_settings_complete(
        candidate_settings
    ):
        return None, None
    cache = VisionCache(
        candidate_settings.vision_cache_path,
        ttl_seconds=candidate_settings.vision_pipeline_cache_ttl_seconds,
    )
    lens_client = (
        SerpApiLensClient(
            api_key=candidate_settings.serpapi_api_key,
            timeout_seconds=candidate_settings.serpapi_lens_timeout_seconds,
            poll_interval_seconds=candidate_settings.serpapi_poll_interval_seconds,
        )
        if candidate_settings.serpapi_lens_enabled and candidate_settings.serpapi_api_key
        else None
    )
    web_client = (
        SerpApiWebClient(
            api_key=candidate_settings.serpapi_api_key,
            timeout_seconds=candidate_settings.serpapi_lens_timeout_seconds,
        )
        if candidate_settings.serpapi_web_fallback_enabled
        and candidate_settings.serpapi_search_enabled
        and candidate_settings.serpapi_api_key
        else None
    )
    pipeline = VisionPipeline(
        preprocessor=ImagePreprocessor(
            timeout_seconds=candidate_settings.vision_model_timeout_seconds,
            max_download_bytes=candidate_settings.vision_pipeline_max_download_bytes,
            max_image_pixels=candidate_settings.vision_pipeline_max_image_pixels,
            model_max_edge=candidate_settings.vision_pipeline_model_max_edge,
        ),
        analyzer=VisualAnalyzer(
            api_base=candidate_settings.vision_model_api_base,
            api_key=candidate_settings.vision_model_api_key,
            model_name=candidate_settings.vision_model_name,
            timeout_seconds=candidate_settings.vision_model_timeout_seconds,
            enable_thinking=False,
            video_fps=candidate_settings.vision_model_video_fps,
        ),
        lens_client=lens_client,
        web_client=web_client,
        cache=cache,
        total_timeout_seconds=candidate_settings.vision_pipeline_timeout_seconds,
        multi_timeout_seconds=candidate_settings.vision_pipeline_multi_timeout_seconds,
        lens_timeout_seconds=candidate_settings.serpapi_lens_timeout_seconds,
        model_timeout_seconds=candidate_settings.vision_model_timeout_seconds,
        lens_concurrency=candidate_settings.serpapi_lens_concurrency,
        max_images=candidate_settings.vision_pipeline_max_images,
        exact_fallback_enabled=candidate_settings.serpapi_exact_fallback_enabled,
        web_fallback_enabled=candidate_settings.serpapi_web_fallback_enabled,
        max_exact_fallbacks=candidate_settings.serpapi_max_exact_fallbacks_per_message,
        max_web_fallbacks=candidate_settings.serpapi_max_web_fallbacks_per_message,
        model_name=candidate_settings.vision_model_name,
        prompt_version="lens-first-prompt-v1",
        lens_parser_version="lens-all-parser-v1",
        schema_version="vision-synthesis-v1",
    )
    return pipeline, cache


storage = Storage(
    settings.database_path,
    context_limit=20,
    default_probability=settings.default_random_reply_probability,
    context_window_seconds=settings.context_window_seconds,
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
vision_client, vision_cache = build_vision_pipeline(settings)
if settings.vision_model_enabled and vision_client is None:
    logger.error("Vision pipeline disabled because Qwen vision settings are incomplete")
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
    vision_client=vision_client,
    trace_logger=DebugTraceLogger(
        root_dir=settings.debug_trace_dir,
        retention_seconds=settings.debug_trace_retention_seconds,
    ),
)
sticker_library = StickerLibrary(
    root=settings.media_sticker_root,
    manifest_path=settings.media_sticker_manifest,
)
reply_enhancer = ReplyEnhancer(
    enabled=settings.media_reply_enabled,
    probability=settings.media_reply_probability,
    library=sticker_library,
)
service.reply_enhancer = reply_enhancer
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
_conversation_locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(asyncio.Lock)
_custom_faces_registration_lock = asyncio.Lock()
_custom_faces_registered = False


async def init_storage() -> None:
    await storage.init()
    if vision_cache is not None:
        await vision_cache.init()


async def close_vision_pipeline() -> None:
    if vision_client is not None:
        await vision_client.close()


class BotCustomFaceClient:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def add_custom_face(self, *, file: str, is_origin: bool = True):
        return await self.bot.call_api("add_custom_face", file=file, is_origin=is_origin)

    async def fetch_custom_face_detail(self, *, count: int = 48):
        return await self.bot.call_api("fetch_custom_face_detail", count=count)


async def register_custom_faces(bot: Bot) -> None:
    if not settings.media_register_custom_faces:
        return
    registrar = CustomFaceRegistrar(
        library=sticker_library,
        cache_path=settings.media_custom_face_cache,
        client=BotCustomFaceClient(bot),
    )
    await registrar.register_all()


async def ensure_custom_faces_registered(bot: Bot) -> None:
    global _custom_faces_registered
    if _custom_faces_registered or not settings.media_register_custom_faces:
        return
    async with _custom_faces_registration_lock:
        if _custom_faces_registered:
            return
        await register_custom_faces(bot)
        _custom_faces_registered = True


try:
    driver = get_driver()
except ValueError:
    driver = None

if driver is not None:
    driver.on_startup(init_storage)
    driver.on_shutdown(close_vision_pipeline)
    if hasattr(driver, "on_bot_connect"):
        driver.on_bot_connect(register_custom_faces)


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


def _has_media(media_urls: MediaUrls) -> bool:
    return bool(media_urls.image_urls or media_urls.video_urls)


def _reply_message_id(event: MessageEvent) -> str:
    message_id = extract_reply_message_id(getattr(event, "message", []))
    if message_id:
        return message_id
    reply = getattr(event, "reply", None)
    for attr in ("message_id", "id"):
        value = getattr(reply, attr, None)
        if value:
            return str(value)
    return ""


def _replied_message_media_urls(event: MessageEvent) -> MediaUrls:
    reply = getattr(event, "reply", None)
    reply_message = getattr(reply, "message", None)
    if reply_message is None:
        return MediaUrls()
    return extract_media_urls(reply_message)


def _message_from_get_msg_result(result) -> list:
    if isinstance(result, dict):
        message = result.get("message", [])
    else:
        message = getattr(result, "message", [])
    return list(message) if message is not None else []


async def fetch_replied_media_urls(bot: Bot, reply_message_id: str) -> MediaUrls:
    if not reply_message_id:
        return MediaUrls()
    try:
        message_id = int(reply_message_id)
    except ValueError:
        return MediaUrls()
    try:
        result = await bot.get_msg(message_id=message_id)
    except Exception:
        return MediaUrls()
    return extract_media_urls(_message_from_get_msg_result(result))


def build_incoming_message(
    event: MessageEvent,
    bot_id: int,
    *,
    fallback_media_urls: MediaUrls | None = None,
    fallback_media_source: str = "",
) -> IncomingMessage | None:
    text = extract_message_text(event)
    if not text:
        return None

    message_segments = getattr(event, "message", [])
    media_urls = extract_media_urls(message_segments)
    repeat_media = extract_repeat_media(message_segments)
    media_source = "current_message" if _has_media(media_urls) else ""
    reply_message_id = _reply_message_id(event)
    if not _has_media(media_urls):
        replied_media_urls = fallback_media_urls or _replied_message_media_urls(event)
        if _has_media(replied_media_urls):
            media_urls = replied_media_urls
            media_source = fallback_media_source or "replied_message"
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
            image_urls=media_urls.image_urls,
            video_urls=media_urls.video_urls,
            media_markers=media_urls.markers,
            media_source=media_source,
            reply_message_id=reply_message_id,
            repeat_media_kind=repeat_media.kind,
            repeat_media_file=repeat_media.file,
            repeat_media_url=repeat_media.url,
            repeat_media_face_id=repeat_media.face_id,
            repeat_media_emoji_id=repeat_media.emoji_id,
            repeat_media_emoji_package_id=repeat_media.emoji_package_id,
            repeat_media_key=repeat_media.key,
            repeat_media_summary=repeat_media.summary,
            repeat_signature=repeat_media.signature,
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
            image_urls=media_urls.image_urls,
            video_urls=media_urls.video_urls,
            media_markers=media_urls.markers,
            media_source=media_source,
            reply_message_id=reply_message_id,
            repeat_media_kind=repeat_media.kind,
            repeat_media_file=repeat_media.file,
            repeat_media_url=repeat_media.url,
            repeat_media_face_id=repeat_media.face_id,
            repeat_media_emoji_id=repeat_media.emoji_id,
            repeat_media_emoji_package_id=repeat_media.emoji_package_id,
            repeat_media_key=repeat_media.key,
            repeat_media_summary=repeat_media.summary,
            repeat_signature=repeat_media.signature,
        )

    return None


def conversation_scope(event: MessageEvent) -> tuple[str, int]:
    message_type = str(getattr(event, "message_type", ""))
    if message_type == "group":
        return ("group", int(getattr(event, "group_id", 0)))
    if message_type == "private":
        return ("private", int(getattr(event, "user_id", 0)))
    return (message_type or "unknown", int(getattr(event, "user_id", 0)))


def render_outgoing_message(message: OutgoingMessage) -> MessageSegment | None:
    if message.kind == "text" and message.text.strip():
        return MessageSegment.text(message.text.strip())
    if message.kind == "image":
        value = message.file.strip() or message.url.strip()
        if not value:
            return None
        if message.image_sub_type is not None or message.summary.strip():
            data: dict[str, object] = {"file": value}
            if message.image_sub_type is not None:
                data["sub_type"] = message.image_sub_type
            if message.summary.strip():
                data["summary"] = message.summary.strip()
            return MessageSegment("image", data)
        return MessageSegment.image(value)
    if message.kind == "face" and message.face_id.strip():
        return MessageSegment.face(int(message.face_id))
    if message.kind == "mface" and not message.is_empty:
        return MessageSegment(
            "mface",
            {
                "emoji_id": message.emoji_id.strip(),
                "emoji_package_id": int(message.emoji_package_id),
                "key": message.key.strip(),
                "summary": message.summary.strip(),
            },
        )
    if message.kind == "record":
        value = message.file.strip() or message.url.strip()
        return MessageSegment.record(value) if value else None
    return None


async def send_outgoing_reply(bot: Bot, event: MessageEvent, reply: OutgoingReply) -> None:
    quote_first_message = (
        getattr(event, "message_type", "") == "group" and reply.source != "repeat"
    )
    first_rendered_message = True
    for outgoing_message in reply.messages:
        segment = render_outgoing_message(outgoing_message)
        if segment is None:
            continue
        if quote_first_message and first_rendered_message:
            await bot.send(event, segment, reply_message=True, at_sender=True)
        else:
            await bot.send(event, segment)
        first_rendered_message = False


async def _service_handle_reply(
    incoming: IncomingMessage,
    *,
    random_value: int,
) -> OutgoingReply | None:
    if hasattr(service, "handle_reply"):
        return await service.handle_reply(incoming, random_value=random_value)
    reply = await service.handle(incoming, random_value=random_value)
    return OutgoingReply.text(reply, source="legacy") if reply else None


@matcher.handle()
async def handle_message(bot: Bot, event: MessageEvent) -> None:
    async with _conversation_locks[conversation_scope(event)]:
        await _handle_message_locked(bot, event)


async def _handle_message_locked(bot: Bot, event: MessageEvent) -> None:
    await ensure_custom_faces_registered(bot)
    incoming = build_incoming_message(event, settings.bot_qq)
    if incoming is not None and not (incoming.image_urls or incoming.video_urls):
        fetched_media_urls = await fetch_replied_media_urls(bot, incoming.reply_message_id)
        if _has_media(fetched_media_urls):
            incoming = build_incoming_message(
                event,
                settings.bot_qq,
                fallback_media_urls=fetched_media_urls,
                fallback_media_source="replied_message_fetch",
            )
    if incoming is None:
        return

    outgoing_reply = await _service_handle_reply(incoming, random_value=random.randrange(100))
    if outgoing_reply is not None and not outgoing_reply.is_empty:
        if voice_service is not None:
            voice = await voice_service.maybe_render(incoming, reply=outgoing_reply.text)
            if voice.file_path is not None:
                await bot.send(event, MessageSegment.record(str(voice.file_path)))
                return
        await send_outgoing_reply(bot, event, outgoing_reply)
