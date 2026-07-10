from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConfidenceBand(StrEnum):
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VisionObservation:
    scene_description: str = ""
    visible_text: tuple[str, ...] = ()
    people_or_characters: tuple[str, ...] = ()
    distinctive_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityCandidate:
    name: str
    entity_type: str
    work_or_affiliation: str = ""
    visual_reason: str = ""
    source_stage: str = ""


@dataclass(frozen=True)
class SearchSource:
    title: str
    url: str
    domain: str
    snippet: str = ""
    result_kind: str = ""


@dataclass(frozen=True)
class LensEvidence:
    exact_matches: tuple[SearchSource, ...] = ()
    visual_matches: tuple[SearchSource, ...] = ()
    repeated_entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateWebEvidence:
    candidate_name: str
    supporting_sources: tuple[SearchSource, ...] = ()
    contradicting_sources: tuple[SearchSource, ...] = ()


@dataclass(frozen=True)
class VisionResolution:
    confidence: ConfidenceBand
    observation: VisionObservation
    candidates: tuple[IdentityCandidate, ...] = ()
    confirmed_identity: IdentityCandidate | None = None
    evidence_summary: str = ""
    uncertainty_reason: str = ""

    @classmethod
    def confirmed(
        cls,
        *,
        observation: VisionObservation,
        identity_name: str,
        work_or_affiliation: str = "",
        entity_type: str = "fictional_character",
        evidence_summary: str = "",
    ) -> VisionResolution:
        identity = IdentityCandidate(
            name=identity_name,
            entity_type=entity_type,
            work_or_affiliation=work_or_affiliation,
            source_stage="resolver",
        )
        return cls(
            confidence=ConfidenceBand.CONFIRMED,
            observation=observation,
            candidates=(identity,),
            confirmed_identity=identity,
            evidence_summary=evidence_summary,
        )

    @classmethod
    def uncertain(
        cls,
        *,
        observation: VisionObservation,
        candidates: tuple[IdentityCandidate, ...] = (),
        evidence_summary: str = "",
        reason: str = "证据不足",
    ) -> VisionResolution:
        return cls(
            confidence=ConfidenceBand.UNCERTAIN,
            observation=observation,
            candidates=candidates,
            evidence_summary=evidence_summary,
            uncertainty_reason=reason,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        observation: VisionObservation,
        reason: str = "",
    ) -> VisionResolution:
        return cls(
            confidence=ConfidenceBand.UNAVAILABLE,
            observation=observation,
            uncertainty_reason=reason,
        )

    def to_context_text(self, *, image_number: int) -> str:
        lines = [f"图片{image_number}："]
        if self.observation.scene_description:
            lines.append(f"视觉观察：{self.observation.scene_description}")
        if self.observation.visible_text:
            lines.append(f"可见文字：{'；'.join(self.observation.visible_text)}")
        if self.confidence is ConfidenceBand.CONFIRMED and self.confirmed_identity is not None:
            identity = self.confirmed_identity
            if identity.work_or_affiliation:
                label = f"《{identity.work_or_affiliation}》中的“{identity.name}”"
            else:
                label = f"“{identity.name}”"
            lines.append(f"身份判断：较可靠地识别为{label}。")
            if self.evidence_summary:
                lines.append(f"判断依据：{self.evidence_summary}")
        elif self.confidence is ConfidenceBand.UNCERTAIN:
            lines.append("身份判断：无法可靠确认。搜索或视觉证据不足，请勿猜测具体身份。")
        else:
            lines.append("身份判断：视觉信息暂不可用，请勿猜测具体身份。")
        return "\n".join(lines)
