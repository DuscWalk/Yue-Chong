from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

if __package__:
    from scripts.probe_vision_pipeline import (
        ProbeConfig,
        ProbeResult,
        load_probe_config,
        run_full_probe,
    )
else:
    from probe_vision_pipeline import (  # type: ignore[import-not-found]
        ProbeConfig,
        ProbeResult,
        load_probe_config,
        run_full_probe,
    )

_CONFIDENCE_LABELS = {"confirmed", "uncertain", "no_identity", "unavailable"}


class EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    image_url: str
    question: str
    expected_any: tuple[str, ...]
    expected_confidence: str


CaseRunner = Callable[[EvaluationCase, ProbeConfig | None], Awaitable[ProbeResult]]


def load_manifest(path: Path, *, formal: bool) -> tuple[EvaluationCase, ...]:
    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationError("could not read manifest") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(data, dict):
            raise EvaluationError(f"line {line_number}: case must be an object")
        case_id = _text(data.get("id"))
        if not case_id:
            raise EvaluationError(f"line {line_number}: id is required")
        if case_id in seen_ids:
            raise EvaluationError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        image_url = _text(data.get("image_url"))
        if not _is_http_url(image_url):
            raise EvaluationError(f"line {line_number}: image_url must be an HTTP(S) URL")
        expected_confidence = _text(data.get("expected_confidence"))
        if expected_confidence not in _CONFIDENCE_LABELS:
            raise EvaluationError(f"line {line_number}: invalid confidence label")
        raw_expected = data.get("expected_any", [])
        if not isinstance(raw_expected, list) or not all(
            isinstance(item, str) for item in raw_expected
        ):
            raise EvaluationError(f"line {line_number}: expected_any must be a string array")
        cases.append(
            EvaluationCase(
                case_id=case_id,
                image_url=image_url,
                question=_text(data.get("question")) or "图中是什么？",
                expected_any=tuple(item.strip() for item in raw_expected if item.strip()),
                expected_confidence=expected_confidence,
            )
        )
    if formal and not 20 <= len(cases) <= 50:
        raise EvaluationError("formal evaluation requires 20 to 50 cases")
    if not cases:
        raise EvaluationError("manifest contains no cases")
    return tuple(cases)


async def default_case_runner(
    case: EvaluationCase,
    config: ProbeConfig | None,
) -> ProbeResult:
    if config is None:
        raise EvaluationError("probe configuration is required")
    return await run_full_probe(config, case.image_url, question=case.question)


async def evaluate_cases(
    cases: tuple[EvaluationCase, ...],
    *,
    config: ProbeConfig | None,
    runner: CaseRunner = default_case_runner,
) -> dict[str, int | float]:
    durations: list[int] = []
    cache_durations: list[int] = []
    counters = {
        "correct_identification": 0,
        "wrong_confirmation": 0,
        "uncertain": 0,
        "no_identity": 0,
        "provider_failure": 0,
        "exact_fallbacks": 0,
        "web_fallbacks": 0,
        "serpapi_queries": 0,
        "cache_hits": 0,
    }
    cold_images = 0
    fallback_cases = 0
    for case in cases:
        result = await runner(case, config)
        durations.append(max(0, result.duration_ms))
        fallback_cases += int(result.exact_fallbacks > 0 or result.web_fallbacks > 0)
        counters["exact_fallbacks"] += int(result.exact_fallbacks > 0)
        counters["web_fallbacks"] += int(result.web_fallbacks > 0)
        counters["serpapi_queries"] += max(0, result.lens_queries)
        if result.cache_hit:
            counters["cache_hits"] += 1
            cache_durations.append(max(0, result.duration_ms))
        else:
            cold_images += 1
        if not result.ok or result.confidence == "unavailable":
            counters["provider_failure"] += 1
            continue
        if result.confidence == "uncertain":
            counters["uncertain"] += 1
            continue
        if result.confidence == "no_identity":
            counters["no_identity"] += 1
            continue
        matched = _matches_expected(result.identity, case.expected_any)
        expected_confirmed = case.expected_confidence == "confirmed"
        if result.confidence == "confirmed" and matched and expected_confirmed:
            counters["correct_identification"] += 1
        elif result.confidence == "confirmed":
            counters["wrong_confirmation"] += 1

    durations.sort()
    cache_durations.sort()
    count = len(cases)
    exact_rate = counters["exact_fallbacks"] / count if count else 0.0
    web_rate = counters["web_fallbacks"] / count if count else 0.0
    return {
        "cases": count,
        **counters,
        "p50_ms": _percentile(durations, 0.50),
        "p90_ms": _percentile(durations, 0.90),
        "p95_ms": _percentile(durations, 0.95),
        "main_path_rate": round(1.0 - fallback_cases / count, 6) if count else 0.0,
        "exact_fallback_rate": round(exact_rate, 6),
        "web_fallback_rate": round(web_rate, 6),
        "serpapi_queries_per_cold_image": (
            round(counters["serpapi_queries"] / cold_images, 6) if cold_images else 0.0
        ),
        "cache_hit_p50_ms": _percentile(cache_durations, 0.50),
    }


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: CaseRunner = default_case_runner,
) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Lens-first vision with a JSONL manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dotenv", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    try:
        cases = load_manifest(args.manifest, formal=not args.dry_run)
        if args.dry_run:
            print(json.dumps({"cases": len(cases), "status": "valid"}, sort_keys=True))
            return 0
        config = load_probe_config(
            dict(os.environ if environ is None else environ),
            dotenv_path=args.dotenv,
        )
        summary = asyncio.run(evaluate_cases(cases, config=config, runner=runner))
    except EvaluationError as exc:
        print(json.dumps({"status": "error", "error_type": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _matches_expected(identity: str, expected: tuple[str, ...]) -> bool:
    normalized = identity.casefold().strip()
    return bool(expected) and any(item.casefold() in normalized for item in expected)


def _is_http_url(value: str) -> bool:
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc) and not parts.username


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _percentile(values: list[int], probability: float) -> int:
    if not values:
        return 0
    rank = max(1, math.ceil(len(values) * probability))
    return values[rank - 1]


if __name__ == "__main__":
    raise SystemExit(main())
