from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def summarize_trace_dir(root: Path) -> dict[str, int]:
    durations: list[int] = []
    confirmed = 0
    uncertain = 0
    unavailable = 0
    timeouts = 0
    cache_hits = 0
    lens_successes = 0
    web_successes = 0

    for path in root.glob("*.jsonl"):
        trace_confidences: list[str] = []
        pipeline_seen = False
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
            if name == "vision.cache.hit" and data.get("stage") == "resolution":
                cache_hits += 1
            elif name == "vision.lens.result" and data.get("ok") is True:
                lens_successes += 1
            elif name == "vision.web.result" and data.get("ok") is True:
                web_successes += 1
            elif name == "vision.resolver.result":
                confidence = data.get("confidence")
                if confidence in {"confirmed", "uncertain", "unavailable"}:
                    trace_confidences.append(str(confidence))
            elif name == "vision.pipeline.result":
                elapsed = data.get("elapsed_ms")
                if isinstance(elapsed, int | float) and elapsed >= 0:
                    durations.append(round(elapsed))
                timeouts += int(data.get("timed_out") is True)
                pipeline_seen = True

        if not pipeline_seen:
            continue
        if "confirmed" in trace_confidences:
            confirmed += 1
        elif "uncertain" in trace_confidences:
            uncertain += 1
        else:
            unavailable += 1

    durations.sort()
    return {
        "count": len(durations),
        "p50_ms": _percentile(durations, 0.50),
        "p90_ms": _percentile(durations, 0.90),
        "p95_ms": _percentile(durations, 0.95),
        "confirmed": confirmed,
        "uncertain": uncertain,
        "unavailable": unavailable,
        "timeouts": timeouts,
        "cache_hits": cache_hits,
        "lens_successes": lens_successes,
        "web_successes": web_successes,
    }


def _percentile(values: list[int], probability: float) -> int:
    if not values:
        return 0
    rank = max(1, math.ceil(len(values) * probability))
    return values[rank - 1]


def _table(summary: dict[str, int]) -> str:
    order = (
        "count",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "confirmed",
        "uncertain",
        "unavailable",
        "timeouts",
        "cache_hits",
        "lens_successes",
        "web_successes",
    )
    width = max(len(key) for key in order)
    return "\n".join(f"{key:<{width}}  {summary[key]}" for key in order)


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
