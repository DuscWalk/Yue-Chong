import json

import httpx
import pytest

from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.image_preprocessor import NormalizedImage
from qq_rolebot.vision_client import VisualAnalyzer
from qq_rolebot.vision_types import LensEvidence, SearchSource


def normalized_image() -> NormalizedImage:
    return NormalizedImage(
        content=b"\x89PNG\r\n\x1a\nnormalized",
        content_type="image/png",
        width=32,
        height=16,
        sha256="a" * 64,
        source_url="https://qq.test/image",
    )


def response_content(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
    )


@pytest.mark.asyncio
async def test_visual_analyzer_sends_question_context_schema_and_image() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "scene_description": "一名银发男性动画角色。",
                "visible_text": ["炎国"],
                "people_or_characters": ["男性动画角色"],
                "distinctive_features": ["银发", "黑色服装"],
                "identity_candidates": [
                    {
                        "name": "重岳",
                        "entity_type": "fictional_character",
                        "work_or_affiliation": "明日方舟",
                        "visual_reason": "服装和画面文字相符",
                    }
                ],
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="vision-secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )

    result = await analyzer.analyze_image(
        normalized_image(),
        user_question="这是谁？",
        chat_context="用户刚才在讨论明日方舟。",
    )

    assert result.error == ""
    assert result.observation.scene_description == "一名银发男性动画角色。"
    assert result.observation.visible_text == ("炎国",)
    assert result.candidates[0].name == "重岳"
    assert result.candidates[0].source_stage == "visual"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["auth"] == "Bearer vision-secret"
    payload = captured["payload"]
    assert payload["temperature"] == 0
    assert payload["enable_thinking"] is False
    assert payload["response_format"]["type"] == "json_schema"
    prompt = payload["messages"][0]["content"][0]["text"]
    assert "这是谁？" in prompt
    assert "明日方舟" in prompt
    assert payload["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


@pytest.mark.asyncio
async def test_visual_analyzer_returns_typed_error_for_malformed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )

    result = await analyzer.analyze_image(
        normalized_image(),
        user_question="这是谁？",
        chat_context="",
    )

    assert result.observation.scene_description == ""
    assert result.candidates == ()
    assert "invalid visual response" in result.error


@pytest.mark.asyncio
async def test_visual_analyzer_describes_dynamic_media_without_identity_candidates() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "scene_description": "有人挥手。",
                "visible_text": [],
                "people_or_characters": ["人物"],
                "distinctive_features": ["挥手动作"],
                "identity_candidates": [{"name": "不应采用", "entity_type": "person"}],
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=3.0,
        transport=httpx.MockTransport(handler),
    )

    result = await analyzer.describe_dynamic_media(
        ["https://example.test/wave.gif"],
        user_question="这个动图在干嘛？",
    )

    assert result.scene_description == "有人挥手。"
    content = captured["payload"]["messages"][0]["content"]
    assert content[1]["type"] == "video_url"
    assert content[1]["fps"] == 3.0


@pytest.mark.asyncio
async def test_visual_analyzer_extracts_candidates_from_bounded_lens_evidence() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "identity_candidates": [
                    {
                        "name": "重岳",
                        "entity_type": "fictional_character",
                        "work_or_affiliation": "明日方舟",
                        "visual_reason": "多个 Lens 标题重复出现该角色与作品",
                    }
                ]
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )
    lens = LensEvidence(
        exact_matches=(
            SearchSource(
                title="重岳 - 明日方舟",
                url="https://example.test/a",
                domain="example.test",
                snippet="角色资料",
                result_kind="exact",
            ),
        )
    )

    candidates = await analyzer.extract_search_candidates(
        lens,
        observation=(await analyzer.analyze_image(
            normalized_image(),
            user_question="这是谁？",
            chat_context="",
        )).observation,
        user_question="这是谁？",
    )

    assert candidates[0].name == "重岳"
    assert candidates[0].source_stage == "lens_extraction"
    raw = json.dumps(captured["payload"], ensure_ascii=False)
    assert "重岳 - 明日方舟" in raw
    assert "https://example.test/a" not in raw


@pytest.mark.asyncio
async def test_visual_analyzer_redacts_data_url_and_api_key_from_trace(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response_content(
            {
                "scene_description": "一只猫。",
                "visible_text": [],
                "people_or_characters": [],
                "distinctive_features": ["猫"],
                "identity_candidates": [],
            }
        )

    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)
    trace = logger.start_trace({"text": "看图"})
    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="vision-secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )

    await analyzer.analyze_image(
        normalized_image(),
        user_question="看图",
        chat_context="",
        trace=trace,
    )

    raw = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "vision.visual.request" in raw
    assert "vision.visual.result" in raw
    assert "vision-secret" not in raw
    assert "bm9ybWFsaXplZA" not in raw
    assert "<redacted" in raw
