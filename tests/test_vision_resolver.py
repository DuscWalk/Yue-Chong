from __future__ import annotations

import pytest

from qq_rolebot.vision_resolver import VisionEvidenceResolver
from qq_rolebot.vision_types import (
    CandidateWebEvidence,
    ConfidenceBand,
    IdentityCandidate,
    LensEvidence,
    SearchSource,
    VisionObservation,
)

OBSERVATION = VisionObservation(
    scene_description="一名银发动画角色。",
    distinctive_features=("银发", "黑色服装"),
)


def candidate(
    *,
    name: str = "重岳",
    entity_type: str = "fictional_character",
    work: str = "明日方舟",
    stage: str = "visual",
) -> IdentityCandidate:
    return IdentityCandidate(
        name=name,
        entity_type=entity_type,
        work_or_affiliation=work,
        visual_reason="画面特征相似",
        source_stage=stage,
    )


def source(domain: str, *, title: str, kind: str = "exact", snippet: str = "") -> SearchSource:
    return SearchSource(
        title=title,
        url=f"https://{domain}/result",
        domain=domain,
        snippet=snippet,
        result_kind=kind,
    )


def resolve(
    *,
    visual_candidates=(),
    exact=(),
    visual=(),
    web=(),
):
    return VisionEvidenceResolver().resolve(
        observation=OBSERVATION,
        visual_candidates=tuple(visual_candidates),
        lens=LensEvidence(exact_matches=tuple(exact), visual_matches=tuple(visual)),
        web_evidence=tuple(web),
    )


@pytest.mark.parametrize(
    "decision",
    [
        resolve(visual_candidates=(candidate(),)),
        resolve(
            visual_candidates=(candidate(),),
            exact=(source("repost.test", title="重岳 图片"),),
        ),
        resolve(
            visual_candidates=(candidate(),),
            exact=(
                source("same.test", title="重岳 明日方舟"),
                source("same.test", title="重岳 角色图"),
            ),
        ),
        resolve(
            visual_candidates=(candidate(),),
            exact=(source("official.test", title="重岳 明日方舟"),),
            web=(
                CandidateWebEvidence(
                    candidate_name="重岳",
                    contradicting_sources=(
                        source("social.test", title="重岳 cosplay", kind="web"),
                    ),
                ),
            ),
        ),
        resolve(
            visual_candidates=(candidate(entity_type="private_person", work=""),),
            exact=(source("social.test", title="张三个人主页"),),
            web=(
                CandidateWebEvidence(
                    candidate_name="重岳",
                    supporting_sources=(
                        source("profile.test", title="张三社交账号", kind="web"),
                    ),
                ),
            ),
        ),
    ],
)
def test_resolver_rejects_weak_conflicting_or_private_identity(decision) -> None:
    assert decision.resolution.confidence is ConfidenceBand.UNCERTAIN
    assert decision.rule_id


def test_resolver_confirms_exact_match_with_independent_web_support() -> None:
    decision = resolve(
        visual_candidates=(candidate(),),
        exact=(source("official.test", title="重岳 - 明日方舟官方角色"),),
        web=(
            CandidateWebEvidence(
                candidate_name="重岳",
                supporting_sources=(
                    source("wiki.test", title="重岳 明日方舟角色资料", kind="web"),
                ),
            ),
        ),
    )

    assert decision.resolution.confidence is ConfidenceBand.CONFIRMED
    assert decision.resolution.confirmed_identity is not None
    assert decision.resolution.confirmed_identity.name == "重岳"
    assert decision.rule_id == "exact_independent_support"


def test_resolver_confirms_repeated_lens_domains_with_web_support() -> None:
    decision = resolve(
        visual_candidates=(candidate(stage="lens_extraction"),),
        visual=(
            source("db-one.test", title="重岳 明日方舟", kind="visual"),
            source("db-two.test", title="明日方舟 重岳", kind="visual"),
        ),
        web=(
            CandidateWebEvidence(
                candidate_name="重岳",
                supporting_sources=(
                    source("official.test", title="重岳 明日方舟", kind="web"),
                ),
            ),
        ),
    )

    assert decision.resolution.confidence is ConfidenceBand.CONFIRMED
    assert decision.rule_id == "repeated_lens_web_support"


def test_select_web_candidates_merges_same_identity_and_respects_limit() -> None:
    resolver = VisionEvidenceResolver()
    selected = resolver.select_web_candidates(
        (
            candidate(stage="visual"),
            candidate(stage="lens_extraction"),
            candidate(name="令", work="明日方舟", stage="lens_extraction"),
        ),
        LensEvidence(),
        limit=1,
    )

    assert len(selected) == 1
    assert selected[0].name == "重岳"
