from __future__ import annotations

from dataclasses import dataclass

from qq_rolebot.vision_types import (
    CandidateWebEvidence,
    ConfidenceBand,
    IdentityCandidate,
    LensEvidence,
    SearchSource,
    VisionObservation,
    VisionResolution,
)

_PRIVATE_ENTITY_TYPES = {"private_person", "unknown_person", "ordinary_person"}


@dataclass(frozen=True)
class ResolverDecision:
    resolution: VisionResolution
    rule_id: str


class VisionEvidenceResolver:
    def select_web_candidates(
        self,
        visual_candidates: tuple[IdentityCandidate, ...],
        lens: LensEvidence,
        *,
        limit: int,
    ) -> tuple[IdentityCandidate, ...]:
        del lens
        unique: dict[tuple[str, str], IdentityCandidate] = {}
        scores: dict[tuple[str, str], int] = {}
        for item in visual_candidates:
            key = self._candidate_key(item)
            if not key[0]:
                continue
            unique.setdefault(key, item)
            scores[key] = scores.get(key, 0) + self._stage_score(item.source_stage)
        ordered = sorted(unique, key=lambda key: (-scores[key], key))
        return tuple(unique[key] for key in ordered[:limit])

    def resolve(
        self,
        *,
        observation: VisionObservation,
        visual_candidates: tuple[IdentityCandidate, ...],
        lens: LensEvidence,
        web_evidence: tuple[CandidateWebEvidence, ...],
    ) -> ResolverDecision:
        candidates = self._merge_candidates(visual_candidates)
        if not candidates:
            return self._uncertain(observation, (), "no_candidate", "没有可验证身份候选")

        web_by_name = {item.candidate_name.casefold(): item for item in web_evidence}
        for item in candidates:
            if item.entity_type.casefold() in _PRIVATE_ENTITY_TYPES:
                continue
            web = web_by_name.get(item.name.casefold(), CandidateWebEvidence(item.name))
            if web.contradicting_sources:
                continue
            exact_domains = self._matching_domains(lens.exact_matches, item)
            web_domains = self._matching_domains(web.supporting_sources, item)
            if exact_domains and web_domains - exact_domains:
                return ResolverDecision(
                    resolution=VisionResolution.confirmed(
                        observation=observation,
                        identity_name=item.name,
                        work_or_affiliation=item.work_or_affiliation,
                        entity_type=item.entity_type,
                        evidence_summary="相同图片结果与独立网页来源一致。",
                    ),
                    rule_id="exact_independent_support",
                )
            visual_domains = self._matching_domains(lens.visual_matches, item)
            if len(visual_domains) >= 2 and web_domains - visual_domains:
                return ResolverDecision(
                    resolution=VisionResolution.confirmed(
                        observation=observation,
                        identity_name=item.name,
                        work_or_affiliation=item.work_or_affiliation,
                        entity_type=item.entity_type,
                        evidence_summary="多个独立相似图来源与网页证据一致。",
                    ),
                    rule_id="repeated_lens_web_support",
                )

        if any(item.entity_type.casefold() in _PRIVATE_ENTITY_TYPES for item in candidates):
            return self._uncertain(
                observation,
                candidates,
                "private_person_refusal",
                "普通或未知真人不进行身份识别",
            )
        if any(
            evidence.contradicting_sources
            for evidence in web_evidence
            if evidence.candidate_name.casefold() in {item.name.casefold() for item in candidates}
        ):
            return self._uncertain(
                observation,
                candidates,
                "conflicting_evidence",
                "搜索证据存在冲突",
            )
        return self._uncertain(
            observation,
            candidates,
            "insufficient_independent_evidence",
            "缺少两个独立可靠来源",
        )

    @classmethod
    def _matching_domains(
        cls,
        sources: tuple[SearchSource, ...],
        candidate: IdentityCandidate,
    ) -> set[str]:
        domains: set[str] = set()
        name = candidate.name.casefold()
        work = candidate.work_or_affiliation.casefold()
        for source in sources:
            combined = f"{source.title} {source.snippet}".casefold()
            if name not in combined:
                continue
            if work and work not in combined:
                continue
            domain = source.domain.strip().casefold()
            if domain:
                domains.add(domain.removeprefix("www."))
        return domains

    @classmethod
    def _merge_candidates(
        cls,
        candidates: tuple[IdentityCandidate, ...],
    ) -> tuple[IdentityCandidate, ...]:
        merged: dict[tuple[str, str], IdentityCandidate] = {}
        score: dict[tuple[str, str], int] = {}
        for item in candidates:
            key = cls._candidate_key(item)
            if not key[0]:
                continue
            merged.setdefault(key, item)
            score[key] = score.get(key, 0) + cls._stage_score(item.source_stage)
        ordered = sorted(merged, key=lambda key: (-score[key], key))
        return tuple(merged[key] for key in ordered)

    @staticmethod
    def _candidate_key(candidate: IdentityCandidate) -> tuple[str, str]:
        return (
            " ".join(candidate.name.casefold().split()),
            " ".join(candidate.work_or_affiliation.casefold().split()),
        )

    @staticmethod
    def _stage_score(stage: str) -> int:
        return 2 if stage == "lens_extraction" else 1

    @staticmethod
    def _uncertain(
        observation: VisionObservation,
        candidates: tuple[IdentityCandidate, ...],
        rule_id: str,
        reason: str,
    ) -> ResolverDecision:
        return ResolverDecision(
            resolution=VisionResolution(
                confidence=ConfidenceBand.UNCERTAIN,
                observation=observation,
                candidates=candidates,
                uncertainty_reason=reason,
            ),
            rule_id=rule_id,
        )
