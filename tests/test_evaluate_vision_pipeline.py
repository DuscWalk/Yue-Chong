from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_vision_pipeline import (
    EvaluationError,
    evaluate_cases,
    load_manifest,
    main,
)
from scripts.probe_vision_pipeline import ProbeResult


def write_manifest(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def cases(count: int = 20) -> list[dict]:
    return [
        {
            "id": f"case-{index:02d}",
            "image_url": f"https://images.test/{index}.jpg?token=private",
            "question": "图中是谁？",
            "expected_any": [f"角色{index}"],
            "expected_confidence": "confirmed",
        }
        for index in range(1, count + 1)
    ]


def test_dry_run_validates_small_manifest_without_provider_calls(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "cases.jsonl"
    write_manifest(manifest, cases(2))
    called = False

    async def runner(case, config):
        nonlocal called
        called = True
        raise AssertionError("dry run must not call providers")

    code = main(["--manifest", str(manifest), "--dry-run"], environ={}, runner=runner)

    assert code == 0
    assert called is False
    assert json.loads(capsys.readouterr().out) == {"cases": 2, "status": "valid"}


@pytest.mark.asyncio
async def test_evaluator_reports_accuracy_fallback_latency_and_query_metrics(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "cases.jsonl"
    write_manifest(manifest, cases())
    loaded = load_manifest(manifest, formal=True)

    async def runner(case, config) -> ProbeResult:
        index = int(case.case_id.split("-")[-1])
        if index == 2:
            return ProbeResult(
                mode="full",
                ok=True,
                duration_ms=200,
                confidence="confirmed",
                identity="错误角色",
                lens_queries=1,
            )
        if index == 3:
            return ProbeResult(
                mode="full",
                ok=True,
                duration_ms=300,
                confidence="uncertain",
                exact_fallbacks=1,
                lens_queries=2,
            )
        if index == 4:
            return ProbeResult(
                mode="full",
                ok=True,
                duration_ms=400,
                confidence="no_identity",
                web_fallbacks=1,
                lens_queries=1,
            )
        if index == 5:
            return ProbeResult(
                mode="full",
                ok=False,
                duration_ms=500,
                confidence="unavailable",
                error_type="timeout",
            )
        return ProbeResult(
            mode="full",
            ok=True,
            duration_ms=index * 100,
            confidence="confirmed",
            identity=f"角色{index}",
            lens_queries=0 if index == 6 else 1,
            cache_hit=index == 6,
        )

    summary = await evaluate_cases(loaded, config=None, runner=runner)

    assert summary["cases"] == 20
    assert summary["correct_identification"] == 16
    assert summary["wrong_confirmation"] == 1
    assert summary["uncertain"] == 1
    assert summary["no_identity"] == 1
    assert summary["provider_failure"] == 1
    assert summary["p50_ms"] == 1000
    assert summary["p90_ms"] == 1800
    assert summary["p95_ms"] == 1900
    assert summary["main_path_rate"] == 0.9
    assert summary["exact_fallback_rate"] == 0.05
    assert summary["web_fallback_rate"] == 0.05
    assert summary["serpapi_queries"] == 19
    assert summary["serpapi_queries_per_cold_image"] == 1.0
    assert summary["cache_hits"] == 1
    assert summary["cache_hit_p50_ms"] == 600


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda rows: rows[:19], "20"),
        (lambda rows: [*rows, {**rows[0]}], "duplicate"),
        (lambda rows: [{**rows[0], "expected_confidence": "maybe"}, *rows[1:]], "confidence"),
        (lambda rows: [{**rows[0], "image_url": "/opt/private/a.jpg"}, *rows[1:]], "HTTP"),
    ],
)
def test_formal_manifest_rejects_invalid_cases(tmp_path: Path, mutator, match: str) -> None:
    manifest = tmp_path / "cases.jsonl"
    write_manifest(manifest, mutator(cases()))

    with pytest.raises(EvaluationError, match=match):
        load_manifest(manifest, formal=True)
