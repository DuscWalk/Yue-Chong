from qq_rolebot.vision_types import (
    ConfidenceBand,
    ExactSearchResult,
    ImageDecision,
    ImageFallbackEvidence,
    ImageLensResult,
    LensAllEvidence,
    LensSearchResult,
    SearchSource,
    VisionSynthesis,
)


def test_lens_first_records_are_immutable_and_keep_normalized_evidence() -> None:
    source = SearchSource(
        title="Synthetic result",
        url="https://example.invalid/result",
        domain="example.invalid",
        snippet="Synthetic snippet",
        result_kind="visual",
    )
    evidence = LensAllEvidence(
        visual_matches=(source,),
        related_content=(source,),
        ai_overview="Synthetic overview",
    )
    search = LensSearchResult(ok=True, evidence=evidence, cached=True)

    assert ImageLensResult(image_number=2, search=search).search.evidence == evidence
    assert ExactSearchResult(ok=True, sources=(source,), cached=True).sources == (source,)
    assert ImageFallbackEvidence(image_number=2, exact_sources=(source,)).image_number == 2


def test_synthesis_context_preserves_order_identity_and_source_fields() -> None:
    synthesis = VisionSynthesis(
        images=(
            ImageDecision(
                image_number=1,
                confidence=ConfidenceBand.CONFIRMED,
                scene_description="一名白发动画角色。",
                visible_text=("ARKNIGHTS",),
                subject_identity="Priestess",
                work_or_affiliation="Arknights",
                source_series_or_author="Arknights official art",
                reason="图像与 Lens 摘要一致。",
            ),
            ImageDecision(
                image_number=2,
                confidence=ConfidenceBand.UNCERTAIN,
                scene_description="黑猫表情包。",
                subject_identity="可能是某个角色",
                reason="结果标题包含多个名字。",
            ),
            ImageDecision(
                image_number=3,
                confidence=ConfidenceBand.NO_IDENTITY,
                scene_description="山水风景。",
            ),
        ),
        combined_answer="第一张是角色图，第二张是表情包，第三张是风景。",
    )

    text = synthesis.to_context_text()

    assert text.index("图片1：") < text.index("图片2：") < text.index("图片3：")
    assert "身份判断：Priestess" in text
    assert "所属作品或阵营：Arknights" in text
    assert "来源系列或作者：Arknights official art" in text
    assert "身份判断：不确定" in text
    assert "可能是某个角色" not in text
    assert "身份判断：图中没有需要确认的具体人物或角色" in text
    assert "多图结论：第一张是角色图，第二张是表情包，第三张是风景。" in text


def test_synthesis_context_does_not_expose_provider_errors_or_urls() -> None:
    synthesis = VisionSynthesis(
        images=(
            ImageDecision(
                image_number=1,
                confidence=ConfidenceBand.UNAVAILABLE,
                scene_description="",
                reason="provider timeout at https://secret.invalid/path?token=secret",
            ),
        ),
        combined_answer="",
    )

    text = synthesis.to_context_text()

    assert "暂不可用" in text
    assert "provider timeout" not in text
    assert "https://" not in text
    assert "token=secret" not in text
