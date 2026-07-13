from __future__ import annotations

import json
from pathlib import Path

from scripts.summarize_vision_traces import summarize_trace_dir


def write_trace(root: Path, name: str, events: list[tuple[str, dict]]) -> None:
    path = root / f"{name}.jsonl"
    path.write_text(
        "\n".join(
            json.dumps({"event": event, "data": data}, ensure_ascii=False)
            for event, data in events
        )
        + "\n",
        encoding="utf-8",
    )


def test_summarizer_reports_lens_first_stage_and_cache_metrics(tmp_path: Path) -> None:
    write_trace(
        tmp_path,
        "one",
        [
            ("vision.cache.hit", {"stage": "lens_all"}),
            ("vision.cache.hit", {"stage": "synthesis"}),
            ("vision.inflight.coalesced", {"stage": "lens_all"}),
            ("vision.lens_all.submit", {"result_type": "all"}),
            ("vision.lens_all.result", {"ok": True, "cached": True, "elapsed_ms": 800}),
            ("vision.synthesis.result", {"ok": True, "elapsed_ms": 200}),
            ("vision.lens_exact.submit", {"result_type": "exact_matches"}),
            ("vision.web_search.result", {"ok": True, "elapsed_ms": 300}),
            ("vision.reevaluation.result", {"ok": True, "elapsed_ms": 100}),
            (
                "vision.pipeline.result",
                {
                    "elapsed_ms": 1000,
                    "timed_out": False,
                    "confidence_counts": {"confirmed": 1, "uncertain": 1},
                },
            ),
        ],
    )
    write_trace(
        tmp_path,
        "two",
        [
            ("vision.lens_all.submit", {"result_type": "all"}),
            ("vision.lens_all.result", {"ok": False, "cached": False, "elapsed_ms": 1800}),
            ("vision.image.failure", {"image_number": 2, "stage": "preprocess"}),
            (
                "vision.pipeline.result",
                {
                    "elapsed_ms": 2000,
                    "timed_out": False,
                    "confidence_counts": {"unavailable": 1},
                },
            ),
        ],
    )
    write_trace(
        tmp_path,
        "three",
        [
            (
                "vision.pipeline.result",
                {
                    "elapsed_ms": 9000,
                    "timed_out": True,
                    "confidence_counts": {"no_identity": 1},
                },
            ),
        ],
    )

    summary = summarize_trace_dir(tmp_path)

    assert summary["count"] == 3
    assert summary["p50_ms"] == 2000
    assert summary["p90_ms"] == 9000
    assert summary["p95_ms"] == 9000
    assert summary["timeouts"] == 1
    assert summary["timeout_rate"] == 1 / 3
    assert summary["confirmed"] == 1
    assert summary["uncertain"] == 1
    assert summary["no_identity"] == 1
    assert summary["unavailable"] == 1
    assert summary["lens_all_submits"] == 2
    assert summary["lens_all_successes"] == 1
    assert summary["lens_all_failures"] == 1
    assert summary["lens_all_cached"] == 1
    assert summary["lens_all_p50_ms"] == 800
    assert summary["lens_all_p95_ms"] == 1800
    assert summary["synthesis_calls"] == 1
    assert summary["reevaluation_calls"] == 1
    assert summary["exact_fallbacks"] == 1
    assert summary["web_fallbacks"] == 1
    assert summary["image_failures"] == 1
    assert summary["lens_cache_hits"] == 1
    assert summary["synthesis_cache_hits"] == 1
    assert summary["inflight_coalesced"] == 1


def test_summarizer_ignores_malformed_lines_and_sensitive_payloads(tmp_path: Path) -> None:
    (tmp_path / "broken.jsonl").write_text(
        '{broken\n'
        + json.dumps(
            {
                "event": "vision.pipeline.result",
                "data": {
                    "elapsed_ms": 123,
                    "timed_out": False,
                    "confirmed_count": 0,
                    "url": "https://signed.test/private?token=secret",
                },
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_trace_dir(tmp_path)
    rendered = json.dumps(summary)

    assert summary["count"] == 1
    assert "signed.test" not in rendered
    assert "token" not in rendered
