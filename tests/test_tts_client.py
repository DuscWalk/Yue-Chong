import base64
import json

import httpx
import pytest

from qq_rolebot.tts_client import TTSClient


@pytest.mark.asyncio
async def test_tts_client_accepts_raw_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/synthesize"
        assert payload["text"] == "hello"
        assert payload["speaker"] == "chongyue"
        return httpx.Response(200, content=b"RIFFdata", headers={"content-type": "audio/wav"})

    client = TTSClient(
        api_url="http://tts.test",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize(
        text="hello",
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )

    assert result.ok is True
    assert result.audio == b"RIFFdata"
    assert result.extension == ".wav"


@pytest.mark.asyncio
async def test_tts_client_accepts_json_base64_audio() -> None:
    audio = base64.b64encode(b"audio-data").decode("ascii")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audio": audio, "format": "mp3"})

    client = TTSClient(
        api_url="http://tts.test",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize(
        text="hello",
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )

    assert result.ok is True
    assert result.audio == b"audio-data"
    assert result.extension == ".mp3"


@pytest.mark.asyncio
async def test_tts_client_returns_failure_for_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    client = TTSClient(
        api_url="http://tts.test",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize(
        text="hello",
        speaker="chongyue",
        style="calm",
        dialect_hint="neutral",
    )

    assert result.ok is False
    assert "503" in result.error


@pytest.mark.asyncio
async def test_gptsovits_backend_posts_to_tts_endpoint() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert request.url.path == "/tts"
        assert payload["text"] == "hello"
        assert payload["text_lang"] == "zh"
        assert payload["ref_audio_path"] == "/opt/refs/cn_001.wav"
        assert payload["prompt_text"] == "reference line"
        assert payload["prompt_lang"] == "zh"
        assert payload["media_type"] == "wav"
        assert payload["streaming_mode"] is False
        return httpx.Response(200, content=b"RIFFgptsovits", headers={"content-type": "audio/wav"})

    client = TTSClient(
        api_url="http://gptsovits.test",
        timeout_seconds=5,
        backend="gptsovits",
        ref_audio_path="/opt/refs/cn_001.wav",
        prompt_text="reference line",
        prompt_lang="zh",
        text_lang="zh",
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize(
        text="hello",
        speaker="chongyue",
        style="calm",
        dialect_hint="southwest",
    )

    assert result.ok is True
    assert result.audio == b"RIFFgptsovits"
    assert result.extension == ".wav"


@pytest.mark.asyncio
async def test_aliyun_cosyvoice_backend_posts_to_speech_synthesizer_and_downloads_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "dashscope.test":
            payload = json.loads(request.content.decode("utf-8"))
            assert request.url.path == "/api/v1/services/audio/tts/SpeechSynthesizer"
            assert request.headers["authorization"] == "Bearer aliyun-key"
            assert payload["model"] == "cosyvoice-v2"
            assert payload["input"]["text"] == "你好"
            assert payload["input"]["voice"] == "chongyue-voice"
            assert payload["input"]["format"] == "mp3"
            assert payload["input"]["sample_rate"] == 24000
            assert payload["input"]["language_hints"] == ["zh"]
            assert "southwest" in payload["input"]["instruction"]
            assert "parameters" not in payload
            return httpx.Response(
                200,
                json={
                    "output": {
                        "audio": {
                            "url": "https://audio.test/generated.mp3",
                        }
                    }
                },
            )

        if request.url.host == "audio.test":
            return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

        raise AssertionError(f"unexpected request: {request.url}")

    client = TTSClient(
        api_url="https://dashscope.test",
        timeout_seconds=5,
        backend="aliyun-cosyvoice",
        api_key="aliyun-key",
        model="cosyvoice-v2",
        audio_format="mp3",
        text_lang="zh",
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize(
        text="你好",
        speaker="chongyue-voice",
        style="calm",
        dialect_hint="southwest",
    )

    assert result.ok is True
    assert result.audio == b"ID3audio"
    assert result.extension == ".mp3"


@pytest.mark.asyncio
async def test_aliyun_cosyvoice_backend_requires_api_key() -> None:
    client = TTSClient(
        api_url="https://dashscope.test",
        timeout_seconds=5,
        backend="aliyun-cosyvoice",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    result = await client.synthesize(
        text="你好",
        speaker="chongyue-voice",
        style="calm",
        dialect_hint="southwest",
    )

    assert result.ok is False
    assert "TTS_API_KEY" in result.error
