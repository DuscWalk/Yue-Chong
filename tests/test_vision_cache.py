from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from qq_rolebot.vision_cache import VisionCache
from qq_rolebot.vision_types import (
    LensEvidence,
    SearchSource,
    VisionObservation,
    VisionResolution,
)


def observation() -> VisionObservation:
    return VisionObservation(
        scene_description="一名动画角色。",
        visible_text=("文字",),
        people_or_characters=("角色",),
        distinctive_features=("银发",),
    )


def lens() -> LensEvidence:
    return LensEvidence(
        exact_matches=(
            SearchSource(
                title="角色资料",
                url="https://example.test/a",
                domain="example.test",
                snippet="作品角色",
                result_kind="exact",
            ),
        ),
        repeated_entities=("角色",),
    )


def resolution() -> VisionResolution:
    return VisionResolution.confirmed(
        observation=observation(),
        identity_name="角色",
        work_or_affiliation="作品",
        evidence_summary="独立来源一致。",
    )


@pytest.mark.asyncio
async def test_resolution_cache_requires_matching_version(tmp_path: Path) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=86_400)
    await cache.init()
    await cache.put_resolution("abc", version="v1", resolution=resolution(), now=100)

    assert await cache.get_resolution("abc", version="v1", now=200) == resolution()
    assert await cache.get_resolution("abc", version="v2", now=200) is None


@pytest.mark.asyncio
async def test_cache_round_trips_observation_and_lens(tmp_path: Path) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=100)
    await cache.init()
    await cache.put_observation("abc", version="v1", observation=observation(), now=10)
    await cache.put_lens("abc", version="v1", lens=lens(), now=10)

    assert await cache.get_observation("abc", version="v1", now=20) == observation()
    assert await cache.get_lens("abc", version="v1", now=20) == lens()


@pytest.mark.asyncio
async def test_cache_expires_and_prunes_rows(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=10)
    await cache.init()
    await cache.put_resolution("old", version="v1", resolution=resolution(), now=1)

    assert await cache.get_resolution("old", version="v1", now=20) is None
    await cache.put_resolution("new", version="v1", resolution=resolution(), now=20)

    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT image_hash FROM vision_cache ORDER BY image_hash").fetchall()
    assert rows == [("new",)]


@pytest.mark.asyncio
async def test_cache_does_not_store_image_signed_url_or_secret(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=100)
    await cache.init()
    await cache.put_resolution("abc", version="v1", resolution=resolution(), now=10)

    raw = path.read_bytes()
    assert b"data:image" not in raw
    assert b"signed.test" not in raw
    assert b"api-secret" not in raw


@pytest.mark.asyncio
async def test_cache_ignores_corrupted_payload(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=100)
    await cache.init()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO vision_cache VALUES (?, ?, ?, ?, ?)",
            ("abc", "resolution", "v1", "{broken", 10),
        )
        db.commit()

    assert await cache.get_resolution("abc", version="v1", now=20) is None
