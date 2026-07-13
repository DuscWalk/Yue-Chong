from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def summarize_trace_dir(root: Path) -> dict[str, int | float]:
    durations: list[int] = []
    lens_durations: list[int] = []
    synthesis_durations: list[int] = []
    reevaluation_durations: list[int] = []
    confidence_counts = {
        "confirmed": 0,
        "uncertain": 0,
        "no_identity": 0,
        "unavailable": 0,
    }
    timeouts = 0
    counters = {
        "lens_all_submits": 0,
        "lens_all_successes": 0,
        "lens_all_failures": 0,
        "lens_all_cached": 0,
        "synthesis_calls": 0,
        "reevaluation_calls": 0,
        "exact_fallbacks": 0,
        "web_fallbacks": 0,
        "image_failures": 0,
        "lens_cache_hits": 0,
        "exact_cache_hits": 0,
        "synthesis_cache_hits": 0,
        "inflight_coalesced": 0,
    }

    for path in root.glob("*.jsonl"):
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw_line)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            name = event.get("event")
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            if name == "vision.cache.hit":
                stage = data.get("stage")
                cache_key = {
                    "lens_all": "lens_cache_hits",
                    "lens_exact": "exact_cache_hits",
                    "synthesis": "synthesis_cache_hits",
                }.get(stage)
                if cache_key:
                    counters[cache_key] += 1
            elif name == "vision.inflight.coalesced":
                counters["inflight_coalesced"] += 1
            elif name == "vision.lens_all.submit":
                counters["lens_all_submits"] += 1
            elif name == "vision.lens_all.result":
                counters[
                    "lens_all_successes" if data.get("ok") is True else "lens_all_failures"
                ] += 1
                counters["lens_all_cached"] += int(data.get("cached") is True)
                _append_duration(lens_durations, data.get("elapsed_ms"))
            elif name == "vision.synthesis.result":
                counters["synthesis_calls"] += 1
                _append_duration(synthesis_durations, data.get("elapsed_ms"))
            elif name == "vision.reevaluation.result":
                counters["reevaluation_calls"] += 1
                _append_duration(reevaluation_durations, data.get("elapsed_ms"))
            elif name == "vision.lens_exact.submit":
                counters["exact_fallbacks"] += 1
            elif name == "vision.web_search.result":
                counters["web_fallbacks"] += 1
            elif name == "vision.image.failure" or (
                name == "vision.image.preprocess" and data.get("ok") is False
            ):
                counters["image_failures"] += 1
            elif name == "vision.pipeline.result":
                _append_duration(durations, data.get("elapsed_ms"))
                timeouts += int(data.get("timed_out") is True)
                raw_counts = data.get("confidence_counts")
                if isinstance(raw_counts, dict):
                    for confidence in confidence_counts:
                        value = raw_counts.get(confidence)
                        if isinstance(value, int) and value >= 0:
                            confidence_counts[confidence] += value

    durations.sort()
    lens_durations.sort()
    synthesis_durations.sort()
    reevaluation_durations.sort()
    count = len(durations)
    return {
        "count": len(durations),
        "p50_ms": _percentile(durations, 0.50),
        "p90_ms": _percentile(durations, 0.90),
        "p95_ms": _percentile(durations, 0.95),
        "timeouts": timeouts,
        "timeout_rate": timeouts / count if count else 0.0,
        **confidence_counts,
        **counters,
        "lens_all_p50_ms": _percentile(lens_durations, 0.50),
        "lens_all_p95_ms": _percentile(lens_durations, 0.95),
        "synthesis_p50_ms": _percentile(synthesis_durations, 0.50),
        "synthesis_p95_ms": _percentile(synthesis_durations, 0.95),
        "reevaluation_p50_ms": _percentile(reevaluation_durations, 0.50),
        "reevaluation_p95_ms": _percentile(reevaluation_durations, 0.95),
    }


def _append_duration(target: list[int], value: Any) -> None:
    if isinstance(value, int | float) and value >= 0:
        target.append(round(value))


def _percentile(values: list[int], probability: float) -> int:
    if not values:
        return 0
    rank = max(1, math.ceil(len(values) * probability))
    return values[rank - 1]


def _table(summary: dict[str, int | float]) -> str:
    order = tuple(summary)
    width = max(len(key) for key in order)
    return "\n".join(f"{key:<{width}}  {_format_value(summary[key])}" for key in order)


def _format_value(value: int | float) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize sanitized vision trace metrics")
    parser.add_argument("trace_dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    summary = summarize_trace_dir(args.trace_dir)
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(_table(summary))


if __name__ == "__main__":
    main()
