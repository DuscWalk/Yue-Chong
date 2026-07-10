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


def test_summarizer_reports_latency_and_decision_metrics(tmp_path: Path) -> None:
    write_trace(
        tmp_path,
        "one",
        [
            ("vision.cache.hit", {"stage": "resolution"}),
            ("vision.lens.result", {"ok": True, "exact_count": 1, "visual_count": 2}),
            ("vision.web.result", {"ok": True, "supporting_count": 1}),
            ("vision.resolver.result", {"confidence": "confirmed", "rule_id": "exact"}),
            (
                "vision.pipeline.result",
                {"elapsed_ms": 1000, "timed_out": False, "confirmed_count": 1},
            ),
        ],
    )
    write_trace(
        tmp_path,
        "two",
        [
            ("vision.resolver.result", {"confidence": "uncertain", "rule_id": "weak"}),
            (
                "vision.pipeline.result",
                {"elapsed_ms": 2000, "timed_out": False, "confirmed_count": 0},
            ),
        ],
    )
    write_trace(
        tmp_path,
        "three",
        [
            (
                "vision.pipeline.result",
                {"elapsed_ms": 9000, "timed_out": True, "confirmed_count": 0},
            ),
        ],
    )

    summary = summarize_trace_dir(tmp_path)

    assert summary["count"] == 3
    assert summary["p50_ms"] == 2000
    assert summary["p90_ms"] == 9000
    assert summary["p95_ms"] == 9000
    assert summary["confirmed"] == 1
    assert summary["uncertain"] == 1
    assert summary["unavailable"] == 1
    assert summary["timeouts"] == 1
    assert summary["cache_hits"] == 1
    assert summary["lens_successes"] == 1
    assert summary["web_successes"] == 1


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
