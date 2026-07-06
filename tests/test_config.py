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
