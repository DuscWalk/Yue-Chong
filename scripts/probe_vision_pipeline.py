from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values

from qq_rolebot.image_preprocessor import ImagePreprocessor
from qq_rolebot.serpapi_client import SerpApiLensClient, SerpApiWebClient
from qq_rolebot.vision_cache import VisionCache
from qq_rolebot.vision_client import VisualAnalyzer
from qq_rolebot.vision_pipeline import VisionPipeline

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DATA_RE = re.compile(r"data:[^\s,;]+(?:;base64)?,\S+", re.IGNORECASE)


@dataclass(frozen=True)
class ProbeConfig:
    serpapi_api_key: str = ""
    vision_model_api_base: str = ""
    vision_model_api_key: str = ""
    vision_model_name: str = ""
    vision_model_timeout_seconds: float = 20.0
    vision_pipeline_timeout_seconds: float = 50.0
    vision_pipeline_multi_timeout_seconds: float = 70.0
    vision_pipeline_model_max_edge: int = 1600
    vision_pipeline_max_download_bytes: int = 10_485_760
    vision_pipeline_max_image_pixels: int = 20_000_000
    vision_cache_path: Path = Path("data/vision_cache.sqlite3")
    serpapi_lens_timeout_seconds: float = 35.0
    serpapi_poll_interval_seconds: float = 0.75
    serpapi_lens_concurrency: int = 2
    exact_fallback_enabled: bool = True
    web_fallback_enabled: bool = True

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.serpapi_api_key, self.vision_model_api_key)
            if value
        )


@dataclass(frozen=True)
class ProbeResult:
    mode: str
    ok: bool
    duration_ms: int = 0
    error_type: str = ""
    visual_matches: int = 0
    related_content: int = 0
    confidence: str = ""
    identity: str = ""
    work_or_affiliation: str = ""
    exact_fallbacks: int = 0
    web_fallbacks: int = 0
    lens_queries: int = 0
    cache_hit: bool = False

    def public_dict(self, *, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "status": "ok" if self.ok else "error",
            "duration_ms": self.duration_ms,
        }
        if not self.ok:
            payload["error_type"] = self.error_type or "provider"
            return payload
        payload.update(
            {
                "visual_matches": self.visual_matches,
                "related_content": self.related_content,
                "confidence": self.confidence,
                "identity": _sanitize_text(self.identity, secrets),
                "work_or_affiliation": _sanitize_text(self.work_or_affiliation, secrets),
                "exact_fallbacks": self.exact_fallbacks,
                "web_fallbacks": self.web_fallbacks,
                "lens_queries": self.lens_queries,
                "cache_hit": self.cache_hit,
            }
        )
        return payload


class ProbeMetricsTrace:
    def __init__(self) -> None:
        self.lens_queries = 0
        self.exact_fallbacks = 0
        self.web_fallbacks = 0
        self.cache_hit = False
        self.error_type = ""

    def event(self, name: str, data: dict[str, Any]) -> None:
        if name == "vision.lens_all.submit":
            self.lens_queries += 1
        elif name == "vision.lens_exact.submit":
            self.lens_queries += 1
            self.exact_fallbacks += 1
        elif name == "vision.web_search.result":
            self.web_fallbacks += 1
        elif name == "vision.cache.hit":
            self.cache_hit = True
        elif name in {"vision.synthesis.result", "vision.reevaluation.result"} and (
            data.get("ok") is False
        ):
            self.error_type = _classify_error(str(data.get("error", "")))
        elif name == "vision.image.failure":
            self.error_type = str(data.get("error_type", "provider"))


ProbeRunner = Callable[[ProbeConfig, str, str], Awaitable[ProbeResult]]


def load_probe_config(
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: Path = Path(".env"),
) -> ProbeConfig:
    environment = dict(os.environ if environ is None else environ)
    file_values = {
        key: value
        for key, value in dotenv_values(dotenv_path).items()
        if isinstance(value, str)
    }
    values = {**file_values, **environment}
    return ProbeConfig(
        serpapi_api_key=values.get("SERPAPI_API_KEY", "").strip(),
        vision_model_api_base=values.get("VISION_MODEL_API_BASE", "").strip(),
        vision_model_api_key=values.get("VISION_MODEL_API_KEY", "").strip(),
        vision_model_name=values.get("VISION_MODEL_NAME", "").strip(),
        vision_model_timeout_seconds=_float(values, "VISION_MODEL_TIMEOUT_SECONDS", 20.0),
        vision_pipeline_timeout_seconds=_float(values, "VISION_PIPELINE_TIMEOUT_SECONDS", 50.0),
        vision_pipeline_multi_timeout_seconds=_float(
            values, "VISION_PIPELINE_MULTI_TIMEOUT_SECONDS", 70.0
        ),
        vision_pipeline_model_max_edge=_int(values, "VISION_PIPELINE_MODEL_MAX_EDGE", 1600),
        vision_pipeline_max_download_bytes=_int(
            values, "VISION_PIPELINE_MAX_DOWNLOAD_BYTES", 10_485_760
        ),
        vision_pipeline_max_image_pixels=_int(
            values, "VISION_PIPELINE_MAX_IMAGE_PIXELS", 20_000_000
        ),
        vision_cache_path=Path(values.get("VISION_CACHE_PATH", "data/vision_cache.sqlite3")),
        serpapi_lens_timeout_seconds=_float(values, "SERPAPI_LENS_TIMEOUT_SECONDS", 35.0),
        serpapi_poll_interval_seconds=_float(
            values, "SERPAPI_POLL_INTERVAL_SECONDS", 0.75
        ),
        serpapi_lens_concurrency=_int(values, "SERPAPI_LENS_CONCURRENCY", 2),
        exact_fallback_enabled=_bool(values, "SERPAPI_EXACT_FALLBACK_ENABLED", True),
        web_fallback_enabled=_bool(values, "SERPAPI_WEB_FALLBACK_ENABLED", True),
    )


async def run_probe(config: ProbeConfig, mode: str, image_url: str) -> ProbeResult:
    return (
        await _run_lens_only(config, image_url)
        if mode == "lens-only"
        else await run_full_probe(config, image_url)
    )


async def _run_lens_only(config: ProbeConfig, image_url: str) -> ProbeResult:
    if not config.serpapi_api_key:
        return ProbeResult(mode="lens-only", ok=False, error_type="configuration")
    client = SerpApiLensClient(
        api_key=config.serpapi_api_key,
        timeout_seconds=config.serpapi_lens_timeout_seconds,
        poll_interval_seconds=config.serpapi_poll_interval_seconds,
    )
    started = time.monotonic()
    try:
        result = await client.search_all(image_url)
    except Exception as exc:
        return ProbeResult(
            mode="lens-only",
            ok=False,
            duration_ms=_elapsed_ms(started),
            error_type=_classify_error(exc),
        )
    finally:
        await client.close()
    if not result.ok:
        return ProbeResult(
            mode="lens-only",
            ok=False,
            duration_ms=_elapsed_ms(started),
            error_type=_classify_error(result.error),
        )
    return ProbeResult(
        mode="lens-only",
        ok=True,
        duration_ms=_elapsed_ms(started),
        visual_matches=len(result.evidence.visual_matches),
        related_content=len(result.evidence.related_content),
        lens_queries=1,
        cache_hit=result.cached,
    )


async def run_full_probe(
    config: ProbeConfig,
    image_url: str,
    *,
    question: str = "请识别图片内容；若有人物或二次元形象，给出人物信息。",
) -> ProbeResult:
    if not all(
        (
            config.vision_model_api_base,
            config.vision_model_api_key,
            config.vision_model_name,
        )
    ):
        return ProbeResult(mode="full", ok=False, error_type="configuration")
    cache = VisionCache(config.vision_cache_path, ttl_seconds=86_400)
    await cache.init()
    lens_client = (
        SerpApiLensClient(
            api_key=config.serpapi_api_key,
            timeout_seconds=config.serpapi_lens_timeout_seconds,
            poll_interval_seconds=config.serpapi_poll_interval_seconds,
        )
        if config.serpapi_api_key
        else None
    )
    web_client = (
        SerpApiWebClient(
            api_key=config.serpapi_api_key,
            timeout_seconds=config.serpapi_lens_timeout_seconds,
        )
        if config.serpapi_api_key and config.web_fallback_enabled
        else None
    )
    pipeline = VisionPipeline(
        preprocessor=ImagePreprocessor(
            timeout_seconds=config.vision_model_timeout_seconds,
            max_download_bytes=config.vision_pipeline_max_download_bytes,
            max_image_pixels=config.vision_pipeline_max_image_pixels,
            model_max_edge=config.vision_pipeline_model_max_edge,
        ),
        analyzer=VisualAnalyzer(
            api_base=config.vision_model_api_base,
            api_key=config.vision_model_api_key,
            model_name=config.vision_model_name,
            timeout_seconds=config.vision_model_timeout_seconds,
            enable_thinking=False,
            video_fps=2.0,
        ),
        lens_client=lens_client,
        web_client=web_client,
        cache=cache,
        total_timeout_seconds=config.vision_pipeline_timeout_seconds,
        multi_timeout_seconds=config.vision_pipeline_multi_timeout_seconds,
        lens_timeout_seconds=config.serpapi_lens_timeout_seconds,
        model_timeout_seconds=config.vision_model_timeout_seconds,
        lens_concurrency=config.serpapi_lens_concurrency,
        max_images=4,
        exact_fallback_enabled=config.exact_fallback_enabled,
        web_fallback_enabled=config.web_fallback_enabled,
        max_exact_fallbacks=2,
        max_web_fallbacks=2,
        model_name=config.vision_model_name,
        prompt_version="lens-first-prompt-v1",
        lens_parser_version="lens-all-parser-v1",
        schema_version="vision-synthesis-v1",
    )
    trace = ProbeMetricsTrace()
    started = time.monotonic()
    try:
        result = await pipeline.describe(
            [image_url],
            user_question=question,
            chat_context="",
            trace=trace,
        )
    except Exception as exc:
        return ProbeResult(
            mode="full",
            ok=False,
            duration_ms=_elapsed_ms(started),
            error_type=_classify_error(exc),
        )
    finally:
        await pipeline.close()
    decision = result.synthesis.images[0] if result.synthesis.images else None
    ok = bool(result.ok and decision and decision.confidence.value != "unavailable")
    error_type = ""
    if not ok:
        error_type = "timeout" if result.timed_out else trace.error_type or "provider"
    return ProbeResult(
        mode="full",
        ok=ok,
        duration_ms=_elapsed_ms(started),
        error_type=error_type,
        confidence=decision.confidence.value if decision else "unavailable",
        identity=decision.subject_identity if decision else "",
        work_or_affiliation=decision.work_or_affiliation if decision else "",
        exact_fallbacks=trace.exact_fallbacks,
        web_fallbacks=trace.web_fallbacks,
        lens_queries=trace.lens_queries,
        cache_hit=trace.cache_hit,
    )


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: ProbeRunner = run_probe,
) -> int:
    parser = argparse.ArgumentParser(description="Run a sanitized Lens-first vision probe")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--lens-only", action="store_true")
    modes.add_argument("--full", action="store_true")
    parser.add_argument("--image-url")
    parser.add_argument("--dotenv", type=Path, default=Path(".env"))
    args = parser.parse_args(argv)
    environment = dict(os.environ if environ is None else environ)
    image_url = args.image_url or environment.get("VISION_PROBE_IMAGE_URL", "")
    if not _is_http_url(image_url):
        parser.error("--image-url or VISION_PROBE_IMAGE_URL must be an HTTP(S) URL")
    mode = "lens-only" if args.lens_only else "full"
    config = load_probe_config(environment, dotenv_path=args.dotenv)
    result = asyncio.run(runner(config, mode, image_url))
    print(
        json.dumps(
            result.public_dict(secrets=config.secrets),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.ok else 1


def _sanitize_text(value: str, secrets: tuple[str, ...]) -> str:
    sanitized = _DATA_RE.sub("[data]", str(value))
    sanitized = _URL_RE.sub("[url]", sanitized)
    for secret in secrets:
        sanitized = sanitized.replace(secret, "[redacted]")
    return " ".join(sanitized.split())[:300]


def _is_http_url(value: str) -> bool:
    parts = urlsplit(value.strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc) and not parts.username


def _classify_error(error: Exception | str) -> str:
    text = str(error).casefold()
    if "401" in text or "403" in text or "auth" in text or "api key" in text:
        return "authentication"
    if "ssl" in text or "tls" in text or "certificate" in text:
        return "tls"
    if "dns" in text or "name or service" in text or "connecterror" in text:
        return "dns"
    if "timeout" in text or "deadline" in text:
        return "timeout"
    if "json" in text or "malformed" in text or "invalid" in text:
        return "malformed"
    return "provider"


def _float(values: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(values.get(key, str(default)))
    except ValueError:
        return default


def _int(values: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(values.get(key, str(default)))
    except ValueError:
        return default


def _bool(values: Mapping[str, str], key: str, default: bool) -> bool:
    raw = values.get(key)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


if __name__ == "__main__":
    raise SystemExit(main())
