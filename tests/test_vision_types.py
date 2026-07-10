from qq_rolebot.vision_types import (
    ConfidenceBand,
    IdentityCandidate,
    VisionObservation,
    VisionResolution,
)


def test_uncertain_resolution_forbids_candidate_as_fact() -> None:
    resolution = VisionResolution(
        confidence=ConfidenceBand.UNCERTAIN,
        observation=VisionObservation(
            scene_description="一名银发动画角色站在雪地里。",
            visible_text=("RHODES",),
            people_or_characters=("动画角色",),
            distinctive_features=("银发", "黑色外套"),
        ),
        candidates=(
            IdentityCandidate(
                name="候选角色",
                entity_type="fictional_character",
                work_or_affiliation="候选作品",
                visual_reason="外观相似",
                source_stage="visual",
            ),
        ),
        confirmed_identity=None,
        evidence_summary="只有视觉相似，没有外部证据。",
        uncertainty_reason="证据不足",
    )

    text = resolution.to_context_text(image_number=1)

    assert "身份判断：无法可靠确认" in text
    assert "候选角色" not in text
    assert "请勿猜测具体身份" in text


def test_confirmed_resolution_includes_verified_identity() -> None:
    resolution = VisionResolution.confirmed(
        observation=VisionObservation(scene_description="动画角色特写。"),
        identity_name="重岳",
        work_or_affiliation="明日方舟",
        evidence_summary="相同图片结果与官方角色页一致。",
    )

    text = resolution.to_context_text(image_number=2)

    assert "图片2" in text
    assert "《明日方舟》中的“重岳”" in text
    assert "相同图片结果与官方角色页一致" in text


def test_unavailable_resolution_formats_failure_without_internal_error() -> None:
    resolution = VisionResolution.unavailable(
        observation=VisionObservation(),
        reason="provider timeout: secret endpoint",
    )

    text = resolution.to_context_text(image_number=1)

    assert "视觉信息暂不可用" in text
    assert "secret endpoint" not in text
