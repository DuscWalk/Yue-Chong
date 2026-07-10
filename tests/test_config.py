from pathlib import Path

import pytest

from qq_rolebot.config import ConfigError, load_settings, parse_int_set, parse_str_list


def complete_env() -> dict[str, str]:
    return {
        "BOT_HOST": "127.0.0.1",
        "BOT_PORT": "8080",
        "ONEBOT_ACCESS_TOKEN": "secret-token",
        "BOT_QQ": "10001",
        "ADMIN_USERS": "10001,10002",
        "GROUP_WHITELIST": "20001",
        "DATABASE_PATH": "data/test.sqlite3",
        "PERSONA_PATH": "personas/default.yaml",
        "MODEL_API_BASE": "https://example.test/v1",
        "MODEL_API_KEY": "model-key",
        "MODEL_NAME": "chat-model",
        "MODEL_TIMEOUT_SECONDS": "15",
        "MAX_OUTPUT_CHARS": "180",
        "DEFAULT_RANDOM_REPLY_PROBABILITY": "8",
        "KEYWORDS": "mika,bot",
        "SENSITIVE_WORDS": "blocked",
    }


def test_parse_int_set_ignores_empty_values() -> None:
    assert parse_int_set("1, 2,,3") == {1, 2, 3}


def test_parse_str_list_trims_empty_values() -> None:
    assert parse_str_list(" hello, ,world ") == ["hello", "world"]


def test_load_settings_from_mapping() -> None:
    settings = load_settings(complete_env())

    assert settings.host == "127.0.0.1"
    assert settings.port == 8080
    assert settings.bot_qq == 10001
    assert settings.admin_users == {10001, 10002}
    assert settings.group_whitelist == {20001}
    assert settings.keywords == ["mika", "bot"]
    assert settings.sensitive_words == ["blocked"]
    assert settings.default_random_reply_probability == 8
    assert settings.repeat_reply_enabled is True
    assert settings.repeat_reply_threshold == 2
    assert settings.context_window_seconds == 600
    assert settings.persona_variant == "dialect"
    assert settings.persona_path.as_posix() == "personas/default_dialect.yaml"


def test_load_settings_reads_standard_persona_variant() -> None:
    env = complete_env()
    env["PERSONA_VARIANT"] = "standard"

    settings = load_settings(env)

    assert settings.persona_variant == "standard"
    assert settings.persona_path.as_posix() == "personas/default.yaml"


def test_load_settings_reads_custom_persona_path() -> None:
    env = complete_env()
    env["PERSONA_VARIANT"] = "custom"
    env["PERSONA_PATH"] = "personas/special.yaml"

    settings = load_settings(env)

    assert settings.persona_variant == "custom"
    assert settings.persona_path.as_posix() == "personas/special.yaml"


def test_load_settings_reads_tool_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.tavily_api_key == ""
    assert settings.tavily_api_base == "https://api.tavily.com"
    assert settings.search_max_results == 5
    assert settings.search_timeout_seconds == 10
    assert settings.search_cooldown_seconds == 20
    assert settings.tools_enable_search is True
    assert settings.tools_enable_persona_sources is True
    assert settings.tools_enable_time is True


def test_load_settings_reads_tool_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "TAVILY_API_KEY": "test-key",
            "TAVILY_API_BASE": "https://search.example.test",
            "SEARCH_MAX_RESULTS": "3",
            "SEARCH_TIMEOUT_SECONDS": "4",
            "SEARCH_COOLDOWN_SECONDS": "7",
            "TOOLS_ENABLE_SEARCH": "false",
            "TOOLS_ENABLE_PERSONA_SOURCES": "0",
            "TOOLS_ENABLE_TIME": "no",
        }
    )

    settings = load_settings(env)

    assert settings.tavily_api_key == "test-key"
    assert settings.tavily_api_base == "https://search.example.test"
    assert settings.search_max_results == 3
    assert settings.search_timeout_seconds == 4
    assert settings.search_cooldown_seconds == 7
    assert settings.tools_enable_search is False
    assert settings.tools_enable_persona_sources is False
    assert settings.tools_enable_time is False


def test_load_settings_reads_repeat_reply_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "REPEAT_REPLY_ENABLED": "false",
            "REPEAT_REPLY_THRESHOLD": "3",
            "CONTEXT_WINDOW_SECONDS": "120",
        }
    )

    settings = load_settings(env)

    assert settings.repeat_reply_enabled is False
    assert settings.repeat_reply_threshold == 3
    assert settings.context_window_seconds == 120


def test_load_settings_reads_media_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.media_reply_enabled is False
    assert settings.media_reply_probability == 0
    assert settings.media_reply_private_probability == 0
    assert settings.media_sticker_root.as_posix() == "stickers"
    assert settings.media_sticker_manifest.as_posix() == "stickers/manifest.yaml"


def test_load_settings_reads_media_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "MEDIA_REPLY_ENABLED": "true",
            "MEDIA_REPLY_PROBABILITY": "35",
            "MEDIA_REPLY_PRIVATE_PROBABILITY": "80",
            "MEDIA_STICKER_ROOT": "/opt/qq-rolebot/stickers",
            "MEDIA_STICKER_MANIFEST": "/opt/qq-rolebot/stickers/custom.yaml",
        }
    )

    settings = load_settings(env)

    assert settings.media_reply_enabled is True
    assert settings.media_reply_probability == 35
    assert settings.media_reply_private_probability == 80
    assert settings.media_sticker_root.as_posix() == "/opt/qq-rolebot/stickers"
    assert settings.media_sticker_manifest.as_posix() == "/opt/qq-rolebot/stickers/custom.yaml"


def test_load_settings_private_media_probability_inherits_global() -> None:
    env = complete_env()
    env["MEDIA_REPLY_PROBABILITY"] = "35"

    settings = load_settings(env)

    assert settings.media_reply_private_probability == 35


def test_load_settings_parses_custom_face_registration_settings() -> None:
    env = complete_env()
    env["MEDIA_REGISTER_CUSTOM_FACES"] = "true"
    env["MEDIA_CUSTOM_FACE_CACHE"] = "data/custom_faces.json"

    settings = load_settings(env)

    assert settings.media_register_custom_faces is True
    assert settings.media_custom_face_cache == Path("data/custom_faces.json")


def test_load_settings_rejects_invalid_media_probability() -> None:
    env = complete_env()
    env["MEDIA_REPLY_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="MEDIA_REPLY_PROBABILITY"):
        load_settings(env)


def test_load_settings_rejects_invalid_private_media_probability() -> None:
    env = complete_env()
    env["MEDIA_REPLY_PRIVATE_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="MEDIA_REPLY_PRIVATE_PROBABILITY"):
        load_settings(env)


def test_load_settings_reads_tts_defaults() -> None:
    settings = load_settings(complete_env())

    assert settings.tts_enabled is False
    assert settings.tts_api_url == ""
    assert settings.tts_timeout_seconds == 20
    assert settings.tts_trigger_keywords == ["语音", "说句话", "念一下", "用你的声音"]
    assert settings.tts_max_chars == 80
    assert settings.tts_cooldown_seconds == 120
    assert settings.tts_cache_dir.name == "voice_cache"
    assert settings.tts_speaker == "chongyue"
    assert settings.tts_style == "calm"
    assert settings.tts_dialect_hint == "neutral"
    assert settings.followup_window_seconds == 90
    assert "你" in settings.followup_trigger_keywords
    assert settings.vision_model_enabled is False
    assert settings.vision_model_api_base == ""
    assert settings.vision_model_api_key == ""
    assert settings.vision_model_name == "qwen3.6-plus"
    assert settings.vision_model_mode == "hybrid"
    assert settings.vision_model_search_input == "data_url"
    assert settings.vision_model_timeout_seconds == 60
    assert settings.vision_model_search_timeout_seconds == 90
    assert settings.vision_model_max_images == 2
    assert settings.vision_model_enable_thinking is True
    assert settings.vision_model_enable_search is True
    assert settings.vision_model_video_fps == 2.0
    assert settings.debug_trace_dir.as_posix() == "data/debug_traces"
    assert settings.debug_trace_retention_seconds == 86_400


def test_load_settings_reads_tts_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "TTS_ENABLED": "true",
            "TTS_API_URL": "http://127.0.0.1:5005",
            "TTS_TIMEOUT_SECONDS": "8",
            "TTS_TRIGGER_KEYWORDS": "发语音,读一下",
            "TTS_MAX_CHARS": "42",
            "TTS_COOLDOWN_SECONDS": "15",
            "TTS_CACHE_DIR": "data/test_voice_cache",
            "TTS_SPEAKER": "test-speaker",
            "TTS_STYLE": "serious",
            "TTS_DIALECT_HINT": "southwest",
            "FOLLOWUP_WINDOW_SECONDS": "45",
            "FOLLOWUP_TRIGGER_KEYWORDS": "你呢,怎么看",
        }
    )

    settings = load_settings(env)

    assert settings.tts_enabled is True
    assert settings.tts_api_url == "http://127.0.0.1:5005"
    assert settings.tts_timeout_seconds == 8
    assert settings.tts_trigger_keywords == ["发语音", "读一下"]
    assert settings.tts_max_chars == 42
    assert settings.tts_cooldown_seconds == 15
    assert str(settings.tts_cache_dir) == "data\\test_voice_cache" or str(
        settings.tts_cache_dir
    ) == "data/test_voice_cache"
    assert settings.tts_speaker == "test-speaker"
    assert settings.tts_style == "serious"
    assert settings.tts_dialect_hint == "southwest"
    assert settings.followup_window_seconds == 45
    assert settings.followup_trigger_keywords == ["你呢", "怎么看"]


def test_load_settings_reads_vision_model_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "VISION_MODEL_ENABLED": "true",
            "VISION_MODEL_API_BASE": "https://vision.example.test/v1",
            "VISION_MODEL_API_KEY": "vision-key",
            "VISION_MODEL_NAME": "qwen3.6-plus",
            "VISION_MODEL_MODE": "search_only",
            "VISION_MODEL_SEARCH_INPUT": "original_url",
            "VISION_MODEL_TIMEOUT_SECONDS": "9",
            "VISION_MODEL_SEARCH_TIMEOUT_SECONDS": "91",
            "VISION_MODEL_MAX_IMAGES": "3",
            "VISION_MODEL_ENABLE_THINKING": "false",
            "VISION_MODEL_ENABLE_SEARCH": "false",
            "VISION_MODEL_VIDEO_FPS": "4.5",
        }
    )

    settings = load_settings(env)

    assert settings.vision_model_enabled is True
    assert settings.vision_model_api_base == "https://vision.example.test/v1"
    assert settings.vision_model_api_key == "vision-key"
    assert settings.vision_model_name == "qwen3.6-plus"
    assert settings.vision_model_mode == "search_only"
    assert settings.vision_model_search_input == "original_url"
    assert settings.vision_model_timeout_seconds == 9
    assert settings.vision_model_search_timeout_seconds == 91
    assert settings.vision_model_max_images == 3
    assert settings.vision_model_enable_thinking is False
    assert settings.vision_model_enable_search is False
    assert settings.vision_model_video_fps == 4.5


def test_load_settings_rejects_invalid_vision_model_mode() -> None:
    env = complete_env()
    env["VISION_MODEL_MODE"] = "fast"

    with pytest.raises(ConfigError, match="VISION_MODEL_MODE"):
        load_settings(env)


def test_load_settings_rejects_invalid_vision_model_search_input() -> None:
    env = complete_env()
    env["VISION_MODEL_SEARCH_INPUT"] = "cdn"

    with pytest.raises(ConfigError, match="VISION_MODEL_SEARCH_INPUT"):
        load_settings(env)


def test_load_settings_reads_debug_trace_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "DEBUG_TRACE_DIR": "data/test_debug_traces",
            "DEBUG_TRACE_RETENTION_SECONDS": "60",
        }
    )

    settings = load_settings(env)

    assert settings.debug_trace_dir.as_posix() == "data/test_debug_traces"
    assert settings.debug_trace_retention_seconds == 60


def test_load_settings_rejects_missing_required_value() -> None:
    env = complete_env()
    env["MODEL_API_KEY"] = ""

    with pytest.raises(ConfigError, match="MODEL_API_KEY"):
        load_settings(env)


def test_load_settings_reads_gptsovits_tts_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "TTS_BACKEND": "gptsovits",
            "TTS_REF_AUDIO_PATH": "/opt/qq-rolebot/data/voice_refs/chongyue/topolect/cn_001.wav",
            "TTS_PROMPT_TEXT": "reference line",
            "TTS_PROMPT_LANG": "zh",
            "TTS_TEXT_LANG": "zh",
        }
    )

    settings = load_settings(env)

    assert settings.tts_backend == "gptsovits"
    assert settings.tts_ref_audio_path is not None
    assert settings.tts_ref_audio_path.parts[-5:] == (
        "data",
        "voice_refs",
        "chongyue",
        "topolect",
        "cn_001.wav",
    )
    assert settings.tts_prompt_text == "reference line"
    assert settings.tts_prompt_lang == "zh"
    assert settings.tts_text_lang == "zh"


def test_load_settings_reads_aliyun_cosyvoice_tts_overrides() -> None:
    env = complete_env()
    env.update(
        {
            "TTS_BACKEND": "aliyun-cosyvoice",
            "TTS_API_KEY": "aliyun-key",
            "TTS_MODEL": "cosyvoice-v2",
            "TTS_AUDIO_FORMAT": "mp3",
        }
    )

    settings = load_settings(env)

    assert settings.tts_backend == "aliyun-cosyvoice"
    assert settings.tts_api_key == "aliyun-key"
    assert settings.tts_model == "cosyvoice-v2"
    assert settings.tts_audio_format == "mp3"


def test_load_settings_rejects_invalid_probability() -> None:
    env = complete_env()
    env["DEFAULT_RANDOM_REPLY_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="DEFAULT_RANDOM_REPLY_PROBABILITY"):
        load_settings(env)


def test_load_settings_rejects_invalid_repeat_reply_threshold() -> None:
    env = complete_env()
    env["REPEAT_REPLY_THRESHOLD"] = "1"

    with pytest.raises(ConfigError, match="REPEAT_REPLY_THRESHOLD"):
        load_settings(env)


def test_load_settings_rejects_invalid_context_window() -> None:
    env = complete_env()
    env["CONTEXT_WINDOW_SECONDS"] = "0"

    with pytest.raises(ConfigError, match="CONTEXT_WINDOW_SECONDS"):
        load_settings(env)


def test_load_settings_rejects_invalid_vision_model_limits() -> None:
    env = complete_env()
    env["VISION_MODEL_TIMEOUT_SECONDS"] = "0"

    with pytest.raises(ConfigError, match="VISION_MODEL_TIMEOUT_SECONDS"):
        load_settings(env)

    env = complete_env()
    env["VISION_MODEL_SEARCH_TIMEOUT_SECONDS"] = "0"

    with pytest.raises(ConfigError, match="VISION_MODEL_SEARCH_TIMEOUT_SECONDS"):
        load_settings(env)

    env = complete_env()
    env["VISION_MODEL_MAX_IMAGES"] = "0"

    with pytest.raises(ConfigError, match="VISION_MODEL_MAX_IMAGES"):
        load_settings(env)

    env = complete_env()
    env["VISION_MODEL_VIDEO_FPS"] = "0"

    with pytest.raises(ConfigError, match="VISION_MODEL_VIDEO_FPS"):
        load_settings(env)

    env = complete_env()
    env["VISION_MODEL_VIDEO_FPS"] = "11"

    with pytest.raises(ConfigError, match="VISION_MODEL_VIDEO_FPS"):
        load_settings(env)


def test_load_settings_rejects_invalid_debug_trace_retention() -> None:
    env = complete_env()
    env["DEBUG_TRACE_RETENTION_SECONDS"] = "0"

    with pytest.raises(ConfigError, match="DEBUG_TRACE_RETENTION_SECONDS"):
        load_settings(env)
