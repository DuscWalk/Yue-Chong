from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from qq_rolebot.debug_trace import DebugTrace
from qq_rolebot.vision_types import (
    CandidateWebEvidence,
    IdentityCandidate,
    LensEvidence,
    SearchSource,
)

_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "ref",
    "source",
    "spm",
}
_CONFLICT_HINTS = (
    "cosplay",
    "coser",
    "同人",
    "fan art",
    "fanart",
    "ai generated",
    "ai生成",
    "相似",
    "lookalike",
    "并非",
    "不是原图",
)


@dataclass(frozen=True)
class LensSearchResult:
    ok: bool
    evidence: LensEvidence = LensEvidence()
    unreachable: bool = False
    error: str = ""


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    filtered = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
            continue
        filtered.append((key, value))
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(filtered),
            "",
        )
    )


def parse_lens_response(
    data: dict[str, Any],
    *,
    exact_limit: int,
    visual_limit: int,
) -> LensEvidence:
    exact = _parse_sources(data.get("exact_matches"), "exact")[:exact_limit]
    visual = _parse_sources(data.get("visual_matches"), "visual")[:visual_limit]
    repeated = _repeated_entities((*exact, *visual))
    return LensEvidence(
        exact_matches=exact,
        visual_matches=visual,
        repeated_entities=repeated,
    )


def _parse_sources(value: Any, result_kind: str) -> tuple[SearchSource, ...]:
    if not isinstance(value, list):
        return ()
    sources: list[SearchSource] = []
    seen_urls: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        raw_url = _text(item.get("link") or item.get("url"))
        if not title or not raw_url:
            continue
        url = canonicalize_url(raw_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        sources.append(
            SearchSource(
                title=title,
                url=url,
                domain=urlsplit(url).netloc.lower(),
                snippet=_text(item.get("snippet") or item.get("source")),
                result_kind=result_kind,
            )
        )
    return tuple(sources)


def _repeated_entities(sources: tuple[SearchSource, ...]) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    order: list[str] = []
    for source in sources:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{1,30}", source.title)
        for token in tokens:
            normalized = token.strip()
            if normalized not in counts:
                order.append(normalized)
            counts[normalized] += 1
    return tuple(token for token in order if counts[token] >= 2)[:10]


class SerpApiLensClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        exact_limit: int,
        visual_limit: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.exact_limit = exact_limit
        self.visual_limit = visual_limit
        self.transport = transport

    async def search(
        self,
        image_url: str,
        *,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> LensSearchResult:
        started = time.monotonic()
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        try:
            exact_data, visual_data = await asyncio.gather(
                self._request(image_url, "exact_matches", timeout),
                self._request(image_url, "visual_matches", timeout),
            )
        except Exception as exc:
            error = _exception_text(exc)
            unreachable = _looks_unreachable(error)
            self._trace_result(
                trace,
                ok=False,
                started=started,
                error=error,
                unreachable=unreachable,
            )
            return LensSearchResult(ok=False, unreachable=unreachable, error=error)

        errors = [
            _text(item.get("error"))
            for item in (exact_data, visual_data)
            if isinstance(item, dict) and item.get("error")
        ]
        if errors:
            error = "; ".join(errors)
            unreachable = _looks_unreachable(error)
            self._trace_result(
                trace,
                ok=False,
                started=started,
                error=error,
                unreachable=unreachable,
            )
            return LensSearchResult(ok=False, unreachable=unreachable, error=error)

        evidence = parse_lens_response(
            {
                "exact_matches": exact_data.get("exact_matches", []),
                "visual_matches": visual_data.get("visual_matches", []),
            },
            exact_limit=self.exact_limit,
            visual_limit=self.visual_limit,
        )
        self._trace_result(trace, ok=True, started=started, evidence=evidence)
        return LensSearchResult(ok=True, evidence=evidence)

    async def _request(self, image_url: str, result_type: str, timeout: float) -> dict[str, Any]:
        params = {
            "engine": "google_lens",
            "url": image_url,
            "type": result_type,
            "api_key": self.api_key,
        }
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            response = await client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid SerpApi Lens response")
        return data

    def _trace_result(
        self,
        trace: DebugTrace | None,
        *,
        ok: bool,
        started: float,
        evidence: LensEvidence | None = None,
        error: str = "",
        unreachable: bool = False,
    ) -> None:
        if trace is None:
            return
        trace.event(
            "vision.lens.result",
            {
                "ok": ok,
                "elapsed_ms": _elapsed_ms(started),
                "exact_count": len(evidence.exact_matches) if evidence else 0,
                "visual_count": len(evidence.visual_matches) if evidence else 0,
                "unreachable": unreachable,
                "error": error,
            },
        )


class SerpApiWebClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    async def verify(
        self,
        candidate: IdentityCandidate,
        *,
        visual_features: tuple[str, ...],
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> CandidateWebEvidence:
        query_parts = [candidate.name]
        if candidate.work_or_affiliation:
            query_parts.append(candidate.work_or_affiliation)
        query_parts.extend(visual_features[:2])
        query = " ".join(part.strip() for part in query_parts if part.strip())[:250]
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
                response = await client.get(
                    "https://serpapi.com/search.json",
                    params={
                        "engine": "google",
                        "q": query,
                        "hl": "zh-cn",
                        "api_key": self.api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()
            evidence = self._parse_web(data, candidate)
        except Exception as exc:
            if trace is not None:
                trace.event(
                    "vision.web.result",
                    {
                        "ok": False,
                        "candidate": candidate.name,
                        "error": _exception_text(exc),
                        "elapsed_ms": _elapsed_ms(started),
                    },
                )
            return CandidateWebEvidence(candidate_name=candidate.name)
        if trace is not None:
            trace.event(
                "vision.web.result",
                {
                    "ok": True,
                    "candidate": candidate.name,
                    "supporting_count": len(evidence.supporting_sources),
                    "contradicting_count": len(evidence.contradicting_sources),
                    "elapsed_ms": _elapsed_ms(started),
                },
            )
        return evidence

    @staticmethod
    def _parse_web(data: Any, candidate: IdentityCandidate) -> CandidateWebEvidence:
        if not isinstance(data, dict):
            return CandidateWebEvidence(candidate_name=candidate.name)
        sources = _parse_sources(data.get("organic_results"), "web")
        supporting: list[SearchSource] = []
        contradicting: list[SearchSource] = []
        candidate_name = candidate.name.casefold()
        affiliation = candidate.work_or_affiliation.casefold()
        for source in sources:
            combined = f"{source.title} {source.snippet}".casefold()
            if any(hint in combined for hint in _CONFLICT_HINTS):
                contradicting.append(source)
            elif candidate_name in combined and (not affiliation or affiliation in combined):
                supporting.append(source)
        return CandidateWebEvidence(
            candidate_name=candidate.name,
            supporting_sources=tuple(supporting),
            contradicting_sources=tuple(contradicting),
        )


def _looks_unreachable(error: str) -> bool:
    lowered = error.casefold()
    return any(token in lowered for token in ("could not fetch", "unreachable", "image url"))


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _exception_text(exc: Exception) -> str:
    return str(exc).strip() or type(exc).__name__


def _elapsed_ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
