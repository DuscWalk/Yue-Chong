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


def test_load_settings_rejects_missing_required_value() -> None:
    env = complete_env()
    env["MODEL_API_KEY"] = ""

    with pytest.raises(ConfigError, match="MODEL_API_KEY"):
        load_settings(env)


def test_load_settings_rejects_invalid_probability() -> None:
    env = complete_env()
    env["DEFAULT_RANDOM_REPLY_PROBABILITY"] = "101"

    with pytest.raises(ConfigError, match="DEFAULT_RANDOM_REPLY_PROBABILITY"):
        load_settings(env)
