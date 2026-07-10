from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid."""


def parse_int_set(raw: str) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        item = part.strip()
        if item:
            values.add(int(item))
    return values


def parse_str_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer") from exc


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{key} must be a boolean")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    onebot_access_token: str
    bot_qq: int
    admin_users: set[int]
    group_whitelist: set[int]
    database_path: Path
    persona_variant: str
    persona_path: Path
    model_api_base: str
    model_api_key: str
    model_name: str
    model_timeout_seconds: int
    max_output_chars: int
    default_random_reply_probability: int
    media_reply_enabled: bool
    media_reply_probability: int
    media_sticker_root: Path
    media_sticker_manifest: Path
    repeat_reply_enabled: bool
    repeat_reply_threshold: int
    context_window_seconds: int
    keywords: list[str]
    sensitive_words: list[str]
    tavily_api_key: str
    tavily_api_base: str
    search_max_results: int
    search_timeout_seconds: int
    search_cooldown_seconds: int
    tools_enable_search: bool
    tools_enable_persona_sources: bool
    tools_enable_time: bool
    tts_enabled: bool
    tts_api_url: str
    tts_timeout_seconds: int
    tts_trigger_keywords: list[str]
    tts_max_chars: int
    tts_cooldown_seconds: int
    tts_cache_dir: Path
    tts_speaker: str
    tts_style: str
    tts_dialect_hint: str
    tts_backend: str
    tts_api_key: str
    tts_model: str
    tts_audio_format: str
    tts_ref_audio_path: Path | None
    tts_prompt_text: str
    tts_prompt_lang: str
    tts_text_lang: str
    vision_model_enabled: bool
    vision_model_api_base: str
    vision_model_api_key: str
    vision_model_name: str
    vision_model_mode: str
    vision_model_search_input: str
    vision_model_timeout_seconds: int
    vision_model_search_timeout_seconds: int
    vision_model_max_images: int
    vision_model_enable_thinking: bool
    vision_model_enable_search: bool
    vision_model_video_fps: float
    debug_trace_dir: Path
    debug_trace_retention_seconds: int
    followup_window_seconds: int
    followup_trigger_keywords: list[str]


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    if env is None:
        load_dotenv()
        env = os.environ

    probability = _int(env, "DEFAULT_RANDOM_REPLY_PROBABILITY", 8)
    if probability < 0 or probability > 100:
        raise ConfigError("DEFAULT_RANDOM_REPLY_PROBABILITY must be between 0 and 100")

    media_reply_probability = _int(env, "MEDIA_REPLY_PROBABILITY", 0)
    if media_reply_probability < 0 or media_reply_probability > 100:
        raise ConfigError("MEDIA_REPLY_PROBABILITY must be between 0 and 100")

    repeat_reply_threshold = _int(env, "REPEAT_REPLY_THRESHOLD", 2)
    if repeat_reply_threshold < 2:
        raise ConfigError("REPEAT_REPLY_THRESHOLD must be greater than or equal to 2")

    context_window_seconds = _int(env, "CONTEXT_WINDOW_SECONDS", 600)
    if context_window_seconds < 1:
        raise ConfigError("CONTEXT_WINDOW_SECONDS must be greater than 0")

    max_output_chars = _int(env, "MAX_OUTPUT_CHARS", 280)
    if max_output_chars < 1:
        raise ConfigError("MAX_OUTPUT_CHARS must be greater than 0")

    timeout = _int(env, "MODEL_TIMEOUT_SECONDS", 20)
    if timeout < 1:
        raise ConfigError("MODEL_TIMEOUT_SECONDS must be greater than 0")

    search_max_results = _int(env, "SEARCH_MAX_RESULTS", 5)
    if search_max_results < 1:
        raise ConfigError("SEARCH_MAX_RESULTS must be greater than 0")

    search_timeout_seconds = _int(env, "SEARCH_TIMEOUT_SECONDS", 10)
    if search_timeout_seconds < 1:
        raise ConfigError("SEARCH_TIMEOUT_SECONDS must be greater than 0")

    search_cooldown_seconds = _int(env, "SEARCH_COOLDOWN_SECONDS", 20)
    if search_cooldown_seconds < 0:
        raise ConfigError("SEARCH_COOLDOWN_SECONDS must be greater than or equal to 0")

    tts_timeout_seconds = _int(env, "TTS_TIMEOUT_SECONDS", 20)
    if tts_timeout_seconds < 1:
        raise ConfigError("TTS_TIMEOUT_SECONDS must be greater than 0")

    vision_model_timeout_seconds = _int(env, "VISION_MODEL_TIMEOUT_SECONDS", 60)
    if vision_model_timeout_seconds < 1:
        raise ConfigError("VISION_MODEL_TIMEOUT_SECONDS must be greater than 0")

    vision_model_search_timeout_seconds = _int(env, "VISION_MODEL_SEARCH_TIMEOUT_SECONDS", 90)
    if vision_model_search_timeout_seconds < 1:
        raise ConfigError("VISION_MODEL_SEARCH_TIMEOUT_SECONDS must be greater than 0")

    vision_model_max_images = _int(env, "VISION_MODEL_MAX_IMAGES", 2)
    if vision_model_max_images < 1:
        raise ConfigError("VISION_MODEL_MAX_IMAGES must be greater than 0")

    vision_model_video_fps = _float(env, "VISION_MODEL_VIDEO_FPS", 2.0)
    if vision_model_video_fps <= 0 or vision_model_video_fps > 10:
        raise ConfigError("VISION_MODEL_VIDEO_FPS must be greater than 0 and at most 10")

    debug_trace_retention_seconds = _int(env, "DEBUG_TRACE_RETENTION_SECONDS", 86_400)
    if debug_trace_retention_seconds < 1:
        raise ConfigError("DEBUG_TRACE_RETENTION_SECONDS must be greater than 0")

    tts_max_chars = _int(env, "TTS_MAX_CHARS", 80)
    if tts_max_chars < 1:
        raise ConfigError("TTS_MAX_CHARS must be greater than 0")

    tts_cooldown_seconds = _int(env, "TTS_COOLDOWN_SECONDS", 120)
    if tts_cooldown_seconds < 0:
        raise ConfigError("TTS_COOLDOWN_SECONDS must be greater than or equal to 0")

    followup_window_seconds = _int(env, "FOLLOWUP_WINDOW_SECONDS", 90)
    if followup_window_seconds < 0:
        raise ConfigError("FOLLOWUP_WINDOW_SECONDS must be greater than or equal to 0")

    tts_backend = env.get("TTS_BACKEND", "generic").strip().lower() or "generic"
    if tts_backend not in {"generic", "gptsovits", "aliyun-cosyvoice"}:
        raise ConfigError("TTS_BACKEND must be one of: generic, gptsovits, aliyun-cosyvoice")

    tts_audio_format = env.get("TTS_AUDIO_FORMAT", "wav").strip().lower() or "wav"
    if tts_audio_format not in {"wav", "mp3"}:
        raise ConfigError("TTS_AUDIO_FORMAT must be one of: wav, mp3")

    vision_model_mode = env.get("VISION_MODEL_MODE", "hybrid").strip().lower() or "hybrid"
    if vision_model_mode not in {"hybrid", "search_only", "media_only"}:
        raise ConfigError("VISION_MODEL_MODE must be one of: hybrid, search_only, media_only")

    vision_model_search_input = (
        env.get("VISION_MODEL_SEARCH_INPUT", "data_url").strip().lower() or "data_url"
    )
    if vision_model_search_input not in {"data_url", "original_url"}:
        raise ConfigError("VISION_MODEL_SEARCH_INPUT must be one of: data_url, original_url")

    raw_tts_ref_audio_path = env.get("TTS_REF_AUDIO_PATH", "").strip()
    persona_variant = env.get("PERSONA_VARIANT", "dialect").strip().lower() or "dialect"
    if persona_variant not in {"dialect", "standard", "custom"}:
        raise ConfigError("PERSONA_VARIANT must be one of: dialect, standard, custom")
    if persona_variant == "dialect":
        persona_path = Path("personas/default_dialect.yaml")
    elif persona_variant == "standard":
        persona_path = Path("personas/default.yaml")
    else:
        persona_path = Path(env.get("PERSONA_PATH", "personas/default.yaml"))

    media_sticker_root = Path(env.get("MEDIA_STICKER_ROOT", "stickers").strip() or "stickers")
    raw_media_manifest = env.get("MEDIA_STICKER_MANIFEST", "").strip()
    media_sticker_manifest = (
        Path(raw_media_manifest) if raw_media_manifest else media_sticker_root / "manifest.yaml"
    )

    admin_users = parse_int_set(_required(env, "ADMIN_USERS"))
    group_whitelist = parse_int_set(_required(env, "GROUP_WHITELIST"))

    return Settings(
        host=env.get("BOT_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int(env, "BOT_PORT", 8080),
        onebot_access_token=_required(env, "ONEBOT_ACCESS_TOKEN"),
        bot_qq=int(_required(env, "BOT_QQ")),
        admin_users=admin_users,
        group_whitelist=group_whitelist,
        database_path=Path(env.get("DATABASE_PATH", "data/rolebot.sqlite3")),
        persona_variant=persona_variant,
        persona_path=persona_path,
        model_api_base=_required(env, "MODEL_API_BASE").rstrip("/"),
        model_api_key=_required(env, "MODEL_API_KEY"),
        model_name=_required(env, "MODEL_NAME"),
        model_timeout_seconds=timeout,
        max_output_chars=max_output_chars,
        default_random_reply_probability=probability,
        media_reply_enabled=_bool(env, "MEDIA_REPLY_ENABLED", False),
        media_reply_probability=media_reply_probability,
        media_sticker_root=media_sticker_root,
        media_sticker_manifest=media_sticker_manifest,
        repeat_reply_enabled=_bool(env, "REPEAT_REPLY_ENABLED", True),
        repeat_reply_threshold=repeat_reply_threshold,
        context_window_seconds=context_window_seconds,
        keywords=parse_str_list(env.get("KEYWORDS", "")),
        sensitive_words=parse_str_list(env.get("SENSITIVE_WORDS", "")),
        tavily_api_key=env.get("TAVILY_API_KEY", "").strip(),
        tavily_api_base=env.get("TAVILY_API_BASE", "https://api.tavily.com").strip().rstrip("/")
        or "https://api.tavily.com",
        search_max_results=search_max_results,
        search_timeout_seconds=search_timeout_seconds,
        search_cooldown_seconds=search_cooldown_seconds,
        tools_enable_search=_bool(env, "TOOLS_ENABLE_SEARCH", True),
        tools_enable_persona_sources=_bool(env, "TOOLS_ENABLE_PERSONA_SOURCES", True),
        tools_enable_time=_bool(env, "TOOLS_ENABLE_TIME", True),
        tts_enabled=_bool(env, "TTS_ENABLED", False),
        tts_api_url=env.get("TTS_API_URL", "").strip().rstrip("/"),
        tts_timeout_seconds=tts_timeout_seconds,
        tts_trigger_keywords=parse_str_list(
            env.get("TTS_TRIGGER_KEYWORDS", "语音,说句话,念一下,用你的声音")
        ),
        tts_max_chars=tts_max_chars,
        tts_cooldown_seconds=tts_cooldown_seconds,
        tts_cache_dir=Path(env.get("TTS_CACHE_DIR", "data/voice_cache")),
        tts_speaker=env.get("TTS_SPEAKER", "chongyue").strip() or "chongyue",
        tts_style=env.get("TTS_STYLE", "calm").strip() or "calm",
        tts_dialect_hint=env.get("TTS_DIALECT_HINT", "neutral").strip() or "neutral",
        tts_backend=tts_backend,
        tts_api_key=env.get("TTS_API_KEY", "").strip(),
        tts_model=env.get("TTS_MODEL", "cosyvoice-v2").strip() or "cosyvoice-v2",
        tts_audio_format=tts_audio_format,
        tts_ref_audio_path=Path(raw_tts_ref_audio_path) if raw_tts_ref_audio_path else None,
        tts_prompt_text=env.get("TTS_PROMPT_TEXT", "").strip(),
        tts_prompt_lang=env.get("TTS_PROMPT_LANG", "zh").strip() or "zh",
        tts_text_lang=env.get("TTS_TEXT_LANG", "zh").strip() or "zh",
        vision_model_enabled=_bool(env, "VISION_MODEL_ENABLED", False),
        vision_model_api_base=env.get("VISION_MODEL_API_BASE", "").strip().rstrip("/"),
        vision_model_api_key=env.get("VISION_MODEL_API_KEY", "").strip(),
        vision_model_name=env.get("VISION_MODEL_NAME", "qwen3.6-plus").strip()
        or "qwen3.6-plus",
        vision_model_mode=vision_model_mode,
        vision_model_search_input=vision_model_search_input,
        vision_model_timeout_seconds=vision_model_timeout_seconds,
        vision_model_search_timeout_seconds=vision_model_search_timeout_seconds,
        vision_model_max_images=vision_model_max_images,
        vision_model_enable_thinking=_bool(env, "VISION_MODEL_ENABLE_THINKING", True),
        vision_model_enable_search=_bool(env, "VISION_MODEL_ENABLE_SEARCH", True),
        vision_model_video_fps=vision_model_video_fps,
        debug_trace_dir=Path(env.get("DEBUG_TRACE_DIR", "data/debug_traces")),
        debug_trace_retention_seconds=debug_trace_retention_seconds,
        followup_window_seconds=followup_window_seconds,
        followup_trigger_keywords=parse_str_list(
            env.get(
                "FOLLOWUP_TRIGGER_KEYWORDS",
                "\u4f60,\u4f60\u89c9\u5f97,\u4f60\u770b,\u600e\u4e48\u770b,"
                "\u548b\u770b,\u600e\u4e48\u6837,\u5982\u4f55,\u8fd9\u4e2a\u5462,"
                "\u90a3\u4e2a\u5462,\u8bf4\u8bdd,\u56de\u8bdd,\u5927\u54e5,"
                "\u91cd\u5cb3,\u5cb3\u997c",
            )
        ),
    )
