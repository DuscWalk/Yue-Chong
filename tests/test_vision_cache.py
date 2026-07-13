from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from qq_rolebot.vision_cache import VisionCache
from qq_rolebot.vision_types import (
    ConfidenceBand,
    ExactSearchResult,
    ImageDecision,
    LensAllEvidence,
    LensSearchResult,
    SearchSource,
    VisionSynthesis,
)


def test_cache_drops_legacy_observation_and_resolution_methods() -> None:
    assert not hasattr(VisionCache, "get_observation")
    assert not hasattr(VisionCache, "put_observation")
    assert not hasattr(VisionCache, "get_lens")
    assert not hasattr(VisionCache, "put_lens")
    assert not hasattr(VisionCache, "get_resolution")
    assert not hasattr(VisionCache, "put_resolution")


def lens_all() -> LensSearchResult:
    return LensSearchResult(
        ok=True,
        evidence=LensAllEvidence(
            visual_matches=(
                SearchSource(
                    title="Synthetic visual result",
                    url="https://signed.test/result?token=private&api_key=api-secret",
                    domain="signed.test",
                    snippet="Synthetic snippet",
                    result_kind="visual",
                ),
            ),
            related_content=(),
            ai_overview="Synthetic overview",
        ),
        cached=False,
    )


def synthesis() -> VisionSynthesis:
    return VisionSynthesis(
        images=(
            ImageDecision(
                image_number=1,
                confidence=ConfidenceBand.CONFIRMED,
                scene_description="Synthetic scene",
                subject_identity="Priestess",
                work_or_affiliation="Arknights",
                source_series_or_author="Official art",
                reason="Image and Lens agree",
            ),
        ),
        combined_answer="Synthetic answer",
    )


@pytest.mark.asyncio
async def test_cache_expires_and_prunes_rows(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=10)
    await cache.init()
    await cache.put_synthesis("old", synthesis=synthesis(), now=1)

    assert await cache.get_synthesis("old", now=20) is None
    await cache.put_synthesis("new", synthesis=synthesis(), now=20)

    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT image_hash FROM vision_cache ORDER BY image_hash").fetchall()
    assert rows == [("new",)]


@pytest.mark.asyncio
async def test_cache_ignores_corrupted_payload(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=100)
    await cache.init()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO vision_cache VALUES (?, ?, ?, ?, ?)",
            ("abc", "synthesis", "lens-first-synthesis-v1", "{broken", 10),
        )
        db.commit()

    assert await cache.get_synthesis("abc", now=20) is None


@pytest.mark.asyncio
async def test_cache_round_trips_lens_all_and_conditional_exact(tmp_path: Path) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=100)
    await cache.init()
    exact = ExactSearchResult(
        ok=True,
        sources=(
            SearchSource(
                title="Synthetic exact result",
                url="https://exact.test/source?token=private",
                domain="exact.test",
                snippet="Exact snippet",
                result_kind="exact",
            ),
        ),
        cached=True,
    )

    await cache.put_lens_all("abc", version="lens-v2", result=lens_all(), now=10)
    await cache.put_exact("abc", version="exact-v1", result=exact, now=10)

    cached_lens = await cache.get_lens_all("abc", version="lens-v2", now=20)
    cached_exact = await cache.get_exact("abc", version="exact-v1", now=20)
    assert cached_lens is not None
    assert cached_lens.evidence.ai_overview == "Synthetic overview"
    assert cached_lens.evidence.visual_matches[0].url == ""
    assert cached_exact is not None
    assert cached_exact.sources[0].domain == "exact.test"
    assert cached_exact.sources[0].url == ""
    assert await cache.get_lens_all("abc", version="lens-v3", now=20) is None


@pytest.mark.asyncio
async def test_combined_synthesis_cache_uses_order_question_context_and_versions(
    tmp_path: Path,
) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=100)
    await cache.init()
    base = {
        "image_hashes": ("a" * 64, "b" * 64),
        "user_question": "比较两张图",
        "chat_context": "最近在讨论明日方舟",
        "model_name": "vision-model",
        "prompt_version": "prompt-v2",
        "lens_parser_version": "lens-v2",
        "schema_version": "schema-v1",
    }
    key = cache.build_synthesis_key(**base)

    await cache.put_synthesis(key, synthesis=synthesis(), now=10)

    assert await cache.get_synthesis(key, now=20) == synthesis()
    reversed_images = {**base, "image_hashes": tuple(reversed(base["image_hashes"]))}
    assert cache.build_synthesis_key(**reversed_images) != key
    assert cache.build_synthesis_key(**{**base, "user_question": "分别是谁"}) != key
    assert cache.build_synthesis_key(**{**base, "chat_context": "最近在讨论别的作品"}) != key
    for field in ("model_name", "prompt_version", "lens_parser_version", "schema_version"):
        assert cache.build_synthesis_key(**{**base, field: f"different-{field}"}) != key


def test_synthesis_key_normalizes_whitespace_and_bounds_chat_context(tmp_path: Path) -> None:
    cache = VisionCache(tmp_path / "vision.sqlite3", ttl_seconds=100)
    common = {
        "image_hashes": ("a" * 64,),
        "model_name": "vision-model",
        "prompt_version": "prompt-v2",
        "lens_parser_version": "lens-v2",
        "schema_version": "schema-v1",
    }
    first = cache.build_synthesis_key(
        **common,
        user_question="  这   是谁  ",
        chat_context="上下文" + "A" * 5000,
    )
    second = cache.build_synthesis_key(
        **common,
        user_question="这 是谁",
        chat_context="上下文" + "A" * 3997 + "B" * 1000,
    )

    assert first == second


@pytest.mark.asyncio
async def test_lens_first_cache_does_not_persist_urls_bytes_or_secrets(tmp_path: Path) -> None:
    path = tmp_path / "vision.sqlite3"
    cache = VisionCache(path, ttl_seconds=100)
    await cache.init()
    key = cache.build_synthesis_key(
        image_hashes=("a" * 64,),
        user_question="这是谁？",
        chat_context="",
        model_name="vision-model",
        prompt_version="prompt-v2",
        lens_parser_version="lens-v2",
        schema_version="schema-v1",
    )

    await cache.put_lens_all("abc", version="lens-v2", result=lens_all(), now=10)
    await cache.put_synthesis(key, synthesis=synthesis(), now=10)

    raw = path.read_bytes()
    assert b"https://" not in raw
    assert b"token=private" not in raw
    assert b"api-secret" not in raw
    assert b"data:image" not in raw
    assert b"base64" not in raw
