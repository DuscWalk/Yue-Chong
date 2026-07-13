import json

import httpx
import pytest

from qq_rolebot.image_preprocessor import NormalizedImage
from qq_rolebot.vision_client import VisualAnalyzer
from qq_rolebot.vision_types import (
    ConfidenceBand,
    ImageDecision,
    ImageFallbackEvidence,
    ImageLensResult,
    LensAllEvidence,
    LensSearchResult,
    SearchSource,
    VisionSynthesis,
)


def test_visual_analyzer_exposes_only_lens_first_static_methods() -> None:
    assert not hasattr(VisualAnalyzer, "analyze_image")
    assert not hasattr(VisualAnalyzer, "extract_search_candidates")


def normalized_image(marker: str = "a") -> NormalizedImage:
    return NormalizedImage(
        content=b"\x89PNG\r\n\x1a\nnormalized-" + marker.encode(),
        content_type="image/png",
        width=32,
        height=16,
        sha256=marker * 64,
        source_url=f"https://qq.test/image-{marker}",
    )


def response_content(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
    )


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
    payload = captured["payload"]
    assert payload["enable_thinking"] is False
    content = payload["messages"][0]["content"]
    assert content[1]["type"] == "video_url"
    assert content[1]["fps"] == 3.0


def lens_result(
    image_number: int,
    *,
    ok: bool = True,
    snippet: str = "角色资料",
) -> ImageLensResult:
    source = SearchSource(
        title=f"图片{image_number}的合成结果",
        url=f"https://lens.example/result-{image_number}?token=private",
        domain="lens.example",
        snippet=snippet,
        result_kind="visual",
    )
    return ImageLensResult(
        image_number=image_number,
        search=LensSearchResult(
            ok=ok,
            evidence=LensAllEvidence(
                visual_matches=(source,) if ok else (),
                related_content=(),
                ai_overview="合成概览" if ok else "",
            ),
            error="could not fetch https://qq.test/private?token=secret" if not ok else "",
            unreachable=not ok,
        ),
    )


@pytest.mark.asyncio
async def test_synthesize_sends_all_images_and_numbered_lens_evidence_once() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "images": [
                    {
                        "image_number": 1,
                        "scene_description": "白发动画角色。",
                        "visible_text": ["ARKNIGHTS"],
                        "subject_identity": "Priestess",
                        "work_or_affiliation": "Arknights",
                        "source_series_or_author": "Arknights official art",
                        "confidence": "confirmed",
                        "reason": "原图与 Lens 结果一致。",
                        "needs_exact": False,
                        "needs_web": False,
                        "verification_query": "",
                    },
                    {
                        "image_number": 2,
                        "scene_description": "黑猫表情包。",
                        "visible_text": [],
                        "subject_identity": "",
                        "work_or_affiliation": "",
                        "source_series_or_author": "某表情包系列",
                        "confidence": "no_identity",
                        "reason": "无需虚构角色名。",
                        "needs_exact": False,
                        "needs_web": True,
                        "verification_query": "黑猫 表情包 来源",
                    },
                ],
                "combined_answer": "第一张是角色图，第二张是表情包。",
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="vision-secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=True,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )

    result = await analyzer.synthesize(
        (normalized_image("a"), normalized_image("b")),
        (
            lens_result(1, snippet="S" * 2000),
            lens_result(2, ok=False),
        ),
        user_question="比较这两张图" + "Q" * 1000,
        chat_context="最近在讨论明日方舟" + "C" * 3000,
        timeout_seconds=4,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["enable_thinking"] is False
    content = payload["messages"][0]["content"]
    image_urls = [item["image_url"]["url"] for item in content if item["type"] == "image_url"]
    assert image_urls == [normalized_image("a").data_url(), normalized_image("b").data_url()]
    prompt = content[0]["text"]
    assert "图片1 Lens 结果" in prompt
    assert "图片2 Lens 不可用" in prompt
    assert "图片1的合成结果" in prompt
    assert "https://lens.example" not in prompt
    assert "token=private" not in prompt
    assert "Q" * 501 not in prompt
    assert "C" * 1501 not in prompt
    schema_properties = payload["response_format"]["json_schema"]["schema"]["properties"]
    image_properties = schema_properties["images"]["items"]["properties"]
    assert set(image_properties) >= {
        "subject_identity",
        "work_or_affiliation",
        "source_series_or_author",
        "confidence",
        "reason",
        "needs_exact",
        "needs_web",
        "verification_query",
    }
    assert result.images[0].confidence is ConfidenceBand.CONFIRMED
    assert result.images[0].subject_identity == "Priestess"
    assert result.images[1].confidence is ConfidenceBand.NO_IDENTITY
    assert result.images[1].needs_web is True
    assert result.combined_answer == "第一张是角色图，第二张是表情包。"


@pytest.mark.asyncio
async def test_synthesize_returns_unavailable_records_for_malformed_response() -> None:
    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not-json"}}]},
            )
        ),
    )

    result = await analyzer.synthesize(
        (normalized_image("a"), normalized_image("b")),
        (lens_result(1), lens_result(2)),
        user_question="这是什么？",
        chat_context="",
        timeout_seconds=4,
    )

    assert [item.image_number for item in result.images] == [1, 2]
    assert all(item.confidence is ConfidenceBand.UNAVAILABLE for item in result.images)
    assert all(not item.reason for item in result.images)


@pytest.mark.asyncio
async def test_reevaluate_is_text_only_and_preserves_image_order() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "images": [
                    {
                        "image_number": 1,
                        "scene_description": "角色图。",
                        "visible_text": [],
                        "subject_identity": "Priestess",
                        "work_or_affiliation": "Arknights",
                        "source_series_or_author": "Official",
                        "confidence": "confirmed",
                        "reason": "exact 结果补充了来源。",
                        "needs_exact": False,
                        "needs_web": False,
                        "verification_query": "",
                    },
                    {
                        "image_number": 2,
                        "scene_description": "表情包。",
                        "visible_text": [],
                        "subject_identity": "",
                        "work_or_affiliation": "",
                        "source_series_or_author": "",
                        "confidence": "uncertain",
                        "reason": "新增结果仍不足。",
                        "needs_exact": False,
                        "needs_web": False,
                        "verification_query": "",
                    },
                ],
                "combined_answer": "第一张已确认，第二张仍不确定。",
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=True,
        video_fps=2.0,
        transport=httpx.MockTransport(handler),
    )
    previous = VisionSynthesis(
        images=(
            ImageDecision(1, ConfidenceBand.UNCERTAIN, needs_exact=True),
            ImageDecision(2, ConfidenceBand.UNCERTAIN, needs_web=True),
        ),
    )
    fallback = ImageFallbackEvidence(
        image_number=1,
        exact_sources=(
            SearchSource(
                title="Synthetic exact result",
                url="https://exact.example/private?token=secret",
                domain="exact.example",
                snippet="Official source",
                result_kind="exact",
            ),
        ),
    )

    result = await analyzer.reevaluate(
        previous,
        (fallback,),
        timeout_seconds=4,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["enable_thinking"] is False
    content = payload["messages"][0]["content"]
    assert all(item["type"] == "text" for item in content)
    raw = json.dumps(payload, ensure_ascii=False)
    assert "data:image" not in raw
    assert "https://exact.example" not in raw
    assert "Synthetic exact result" in raw
    assert [item.image_number for item in result.images] == [1, 2]


def test_parse_synthesis_keeps_valid_image_when_another_record_is_invalid() -> None:
    result = VisualAnalyzer._parse_synthesis(
        {
            "images": [
                {
                    "image_number": 1,
                    "scene_description": "有效图片。",
                    "visible_text": [],
                    "subject_identity": "Priestess",
                    "work_or_affiliation": "Arknights",
                    "source_series_or_author": "Official",
                    "confidence": "confirmed",
                    "reason": "有效",
                    "needs_exact": False,
                    "needs_web": False,
                    "verification_query": "",
                },
                {
                    "image_number": 2,
                    "scene_description": "无效图片。",
                    "visible_text": [],
                    "subject_identity": "猜测",
                    "work_or_affiliation": "",
                    "source_series_or_author": "",
                    "confidence": "definitely",
                    "reason": "无效 confidence",
                    "needs_exact": False,
                    "needs_web": False,
                    "verification_query": "",
                },
            ],
            "combined_answer": "第一张有效。",
        },
        image_numbers=(1, 2),
    )

    assert result.images[0].confidence is ConfidenceBand.CONFIRMED
    assert result.images[0].subject_identity == "Priestess"
    assert result.images[1].confidence is ConfidenceBand.UNAVAILABLE


def test_parse_synthesis_removes_urls_from_persistable_model_output() -> None:
    result = VisualAnalyzer._parse_synthesis(
        {
            "images": [
                {
                    "image_number": 1,
                    "scene_description": "来源 https://qq.test/image?token=private",
                    "visible_text": ["https://qq.test/text?token=private"],
                    "subject_identity": "Priestess",
                    "work_or_affiliation": "Arknights",
                    "source_series_or_author": "https://source.test/private",
                    "confidence": "confirmed",
                    "reason": "来自 https://qq.test/image?token=private",
                    "needs_exact": False,
                    "needs_web": False,
                    "verification_query": "site:https://qq.test/private Priestess",
                }
            ],
            "combined_answer": "参见 https://qq.test/image?token=private",
        },
        image_numbers=(1,),
    )

    raw = json.dumps(result, default=lambda item: item.__dict__, ensure_ascii=False)
    assert "https://" not in raw
    assert "token=private" not in raw


@pytest.mark.asyncio
async def test_synthesize_preserves_non_contiguous_original_image_numbers() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return response_content(
            {
                "images": [
                    {
                        "image_number": image_number,
                        "scene_description": f"图片{image_number}",
                        "visible_text": [],
                        "subject_identity": "",
                        "work_or_affiliation": "",
                        "source_series_or_author": "",
                        "confidence": "no_identity",
                        "reason": "",
                        "needs_exact": False,
                        "needs_web": False,
                        "verification_query": "",
                    }
                    for image_number in (1, 3)
                ],
                "combined_answer": "",
            }
        )

    analyzer = VisualAnalyzer(
        api_base="https://vision.test/v1",
        api_key="secret",
        model_name="vision-model",
        timeout_seconds=5,
        enable_thinking=False,
        video_fps=2,
        transport=httpx.MockTransport(handler),
    )

    result = await analyzer.synthesize(
        (normalized_image("a"), normalized_image("c")),
        (lens_result(1), lens_result(3)),
        user_question="分别是什么？",
        chat_context="",
        timeout_seconds=4,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    markers = [
        item["text"]
        for item in payload["messages"][0]["content"]
        if item["type"] == "text" and item["text"].endswith("原图：")
    ]
    assert markers == ["图片1原图：", "图片3原图："]
    assert [item.image_number for item in result.images] == [1, 3]
