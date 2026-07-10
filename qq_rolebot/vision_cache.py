from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import aiosqlite

from qq_rolebot.vision_types import (
    ConfidenceBand,
    IdentityCandidate,
    LensEvidence,
    SearchSource,
    VisionObservation,
    VisionResolution,
)


class VisionCache:
    def __init__(self, path: Path, *, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS vision_cache (
                    image_hash TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (image_hash, stage, version)
                )
                """
            )
            await db.commit()

    async def get_observation(
        self,
        image_hash: str,
        *,
        version: str,
        now: int,
    ) -> VisionObservation | None:
        data = await self._get(image_hash, stage="observation", version=version, now=now)
        return self._decode_observation(data) if data is not None else None

    async def put_observation(
        self,
        image_hash: str,
        *,
        version: str,
        observation: VisionObservation,
        now: int,
    ) -> None:
        await self._put(
            image_hash,
            stage="observation",
            version=version,
            payload=asdict(observation),
            now=now,
        )

    async def get_lens(
        self,
        image_hash: str,
        *,
        version: str,
        now: int,
    ) -> LensEvidence | None:
        data = await self._get(image_hash, stage="lens", version=version, now=now)
        return self._decode_lens(data) if data is not None else None

    async def put_lens(
        self,
        image_hash: str,
        *,
        version: str,
        lens: LensEvidence,
        now: int,
    ) -> None:
        await self._put(
            image_hash,
            stage="lens",
            version=version,
            payload=asdict(lens),
            now=now,
        )

    async def get_resolution(
        self,
        image_hash: str,
        *,
        version: str,
        now: int,
    ) -> VisionResolution | None:
        data = await self._get(image_hash, stage="resolution", version=version, now=now)
        return self._decode_resolution(data) if data is not None else None

    async def put_resolution(
        self,
        image_hash: str,
        *,
        version: str,
        resolution: VisionResolution,
        now: int,
    ) -> None:
        await self._put(
            image_hash,
            stage="resolution",
            version=version,
            payload=asdict(resolution),
            now=now,
        )

    async def _get(
        self,
        image_hash: str,
        *,
        stage: str,
        version: str,
        now: int,
    ) -> dict[str, Any] | None:
        cutoff = now - self.ttl_seconds
        async with aiosqlite.connect(self.path) as db:
            rows = await db.execute_fetchall(
                """
                SELECT payload_json, created_at
                FROM vision_cache
                WHERE image_hash = ? AND stage = ? AND version = ?
                """,
                (image_hash, stage, version),
            )
        if not rows or int(rows[0][1]) < cutoff:
            return None
        try:
            data = json.loads(str(rows[0][0]))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def _put(
        self,
        image_hash: str,
        *,
        stage: str,
        version: str,
        payload: dict[str, Any],
        now: int,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        cutoff = now - self.ttl_seconds
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM vision_cache WHERE created_at < ?", (cutoff,))
            await db.execute(
                """
                INSERT INTO vision_cache(image_hash, stage, version, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(image_hash, stage, version) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (image_hash, stage, version, encoded, now),
            )
            await db.commit()

    @staticmethod
    def _decode_observation(data: dict[str, Any]) -> VisionObservation | None:
        try:
            return VisionObservation(
                scene_description=str(data.get("scene_description", "")),
                visible_text=tuple(str(item) for item in data.get("visible_text", [])),
                people_or_characters=tuple(
                    str(item) for item in data.get("people_or_characters", [])
                ),
                distinctive_features=tuple(
                    str(item) for item in data.get("distinctive_features", [])
                ),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _decode_lens(cls, data: dict[str, Any]) -> LensEvidence | None:
        try:
            return LensEvidence(
                exact_matches=cls._decode_sources(data.get("exact_matches")),
                visual_matches=cls._decode_sources(data.get("visual_matches")),
                repeated_entities=tuple(str(item) for item in data.get("repeated_entities", [])),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _decode_resolution(cls, data: dict[str, Any]) -> VisionResolution | None:
        try:
            observation = cls._decode_observation(data.get("observation", {}))
            if observation is None:
                return None
            candidates = cls._decode_candidates(data.get("candidates"))
            confirmed_data = data.get("confirmed_identity")
            confirmed = (
                cls._decode_candidate(confirmed_data) if isinstance(confirmed_data, dict) else None
            )
            return VisionResolution(
                confidence=ConfidenceBand(str(data["confidence"])),
                observation=observation,
                candidates=candidates,
                confirmed_identity=confirmed,
                evidence_summary=str(data.get("evidence_summary", "")),
                uncertainty_reason=str(data.get("uncertainty_reason", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def _decode_sources(cls, value: Any) -> tuple[SearchSource, ...]:
        if not isinstance(value, list):
            return ()
        sources = []
        for item in value:
            if not isinstance(item, dict):
                continue
            sources.append(
                SearchSource(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    domain=str(item.get("domain", "")),
                    snippet=str(item.get("snippet", "")),
                    result_kind=str(item.get("result_kind", "")),
                )
            )
        return tuple(sources)

    @classmethod
    def _decode_candidates(cls, value: Any) -> tuple[IdentityCandidate, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            candidate
            for item in value
            if isinstance(item, dict) and (candidate := cls._decode_candidate(item)) is not None
        )

    @staticmethod
    def _decode_candidate(data: dict[str, Any]) -> IdentityCandidate | None:
        name = str(data.get("name", "")).strip()
        entity_type = str(data.get("entity_type", "")).strip()
        if not name or not entity_type:
            return None
        return IdentityCandidate(
            name=name,
            entity_type=entity_type,
            work_or_affiliation=str(data.get("work_or_affiliation", "")),
            visual_reason=str(data.get("visual_reason", "")),
            source_stage=str(data.get("source_stage", "")),
        )
