from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from qq_rolebot.debug_trace import DebugTrace


@dataclass(frozen=True)
class VisionResult:
    ok: bool
    summary: str | None = None
    error: str | None = None


class VisionClient:
    def __init__(
        self,
        *,
        api_base: str,
        api_key: str,
        model_name: str,
        timeout_seconds: int,
        max_images: int,
        enable_thinking: bool = True,
        enable_search: bool = True,
        video_fps: float = 2.0,
        search_after_media_timeout_seconds: float = 12.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.max_images = max_images
        self.enable_thinking = enable_thinking
        self.enable_search = enable_search
        self.video_fps = video_fps
        self.search_after_media_timeout_seconds = search_after_media_timeout_seconds
        self.transport = transport

    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
        trace: DebugTrace | None = None,
    ) -> VisionResult:
        images = self._http_urls(image_urls)[: self.max_images]
        videos = self._http_urls(video_urls or [])[: self.max_images]
        self._trace(
            trace,
            "vision.describe.start",
            {
                "image_urls": images,
                "video_urls": videos,
                "max_images": self.max_images,
                "enable_thinking": self.enable_thinking,
                "enable_search": self.enable_search,
                "video_fps": self.video_fps,
            },
        )
        if not images and not videos:
            self._trace(trace, "vision.describe.result", {"ok": False, "error": "no media urls"})
            return VisionResult(ok=False, error="no media urls")

        summaries: list[str] = []
        errors: list[str] = []

        media = await self._describe_media(images, videos, trace=trace)
        has_media_summary = False
        if media.ok and media.summary:
            has_media_summary = True
            summaries.append(media.summary)
        elif media.error:
            errors.append(media.error)

        search = await self._search_images_with_timeout(
            images,
            videos,
            trace=trace,
            timeout_seconds=(
                self.search_after_media_timeout_seconds if has_media_summary else None
            ),
        )
        if search.ok and search.summary:
            summaries.append(search.summary)
        elif search.error:
            errors.append(search.error)

        if summaries:
            summary = "\n".join(summaries)
            self._trace(trace, "vision.describe.result", {"ok": True, "summary": summary})
            return VisionResult(ok=True, summary=summary)
        error = "; ".join(errors) or "empty vision response"
        self._trace(trace, "vision.describe.result", {"ok": False, "error": error})
        return VisionResult(ok=False, error=error)

    async def _describe_media(
        self,
        image_urls: list[str],
        video_urls: list[str],
        *,
        trace: DebugTrace | None,
    ) -> VisionResult:
        image_inputs = await self._image_input_urls(image_urls, trace=trace)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "请用简体中文客观概括这些聊天图片、表情包、动图或视频。"
                    "如果能从画面、文字、标识或常识可靠识别作品、角色、人物、物品、地点或梗图来源，"
                    "请先给出具体名称和判断依据。用户问“是谁”“哪个”“什么”时，优先回答可识别名称。"
                    "再描述可见内容、文字、动作和情绪。不要扮演角色，不要只凭相似风格或主观猜测。"
                    "看不清或无法识别时请明确说不确定。140字以内。"
                ),
            }
        ]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_inputs)
        content.extend(
            {
                "type": "video_url",
                "video_url": {"url": url},
                "fps": self.video_fps,
            }
            for url in video_urls
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "enable_thinking": self.enable_thinking,
        }
        self._trace(
            trace,
            "vision.media.request",
            {"path": "/chat/completions", "payload": payload},
        )

        started = time.monotonic()
        try:
            data = await self._post_json("/chat/completions", payload)
        except Exception as exc:
            error = self._exception_text(exc)
            self._trace(
                trace,
                "vision.media.result",
                {
                    "ok": False,
                    "error": error,
                    "error_type": type(exc).__name__,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error=error)

        try:
            summary = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            self._trace(
                trace,
                "vision.media.result",
                {
                    "ok": False,
                    "error": f"invalid vision response: {exc}",
                    "response": data,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error=f"invalid vision response: {exc}")

        text = str(summary).strip()
        if not text:
            self._trace(
                trace,
                "vision.media.result",
                {
                    "ok": False,
                    "error": "empty vision response",
                    "response": data,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error="empty vision response")
        self._trace(
            trace,
            "vision.media.result",
            {
                "ok": True,
                "summary": text,
                "response": data,
                "elapsed_ms": self._elapsed_ms(started),
            },
        )
        return VisionResult(ok=True, summary=text)

    async def _search_images_with_timeout(
        self,
        image_urls: list[str],
        video_urls: list[str],
        *,
        trace: DebugTrace | None,
        timeout_seconds: float | None,
    ) -> VisionResult:
        if timeout_seconds is None:
            return await self._search_images(image_urls, video_urls, trace=trace)

        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._search_images(image_urls, video_urls, trace=trace),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            self._trace(
                trace,
                "vision.search.result",
                {
                    "ok": False,
                    "error": "opportunistic vision search timed out",
                    "error_type": "TimeoutError",
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error="opportunistic vision search timed out")

    async def _search_images(
        self,
        image_urls: list[str],
        video_urls: list[str],
        *,
        trace: DebugTrace | None,
    ) -> VisionResult:
        if not self.enable_search:
            self._trace(trace, "vision.search.skipped", {"reason": "vision search disabled"})
            return VisionResult(ok=False, error="vision search disabled")

        search_urls = [*image_urls, *[url for url in video_urls if self._is_gif_url(url)]]
        search_urls = search_urls[: self.max_images]
        if not search_urls:
            self._trace(trace, "vision.search.skipped", {"reason": "no searchable image urls"})
            return VisionResult(ok=False, error="no searchable image urls")

        content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "请联网或图搜判断这些聊天图片/表情包可能的来源、梗图含义或相关背景。"
                    "如果没有可靠结果，请明确说不确定。80字以内。"
                ),
            }
        ]
        content.extend({"type": "input_image", "image_url": url} for url in search_urls)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": [{"role": "user", "content": content}],
            "tools": [{"type": "image_search"}, {"type": "web_search"}],
            "enable_thinking": self.enable_thinking,
        }
        self._trace(trace, "vision.search.request", {"path": "/responses", "payload": payload})

        started = time.monotonic()
        try:
            data = await self._post_json("/responses", payload)
        except Exception as exc:
            error = self._exception_text(exc)
            self._trace(
                trace,
                "vision.search.result",
                {
                    "ok": False,
                    "error": error,
                    "error_type": type(exc).__name__,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error=error)

        text = self._response_text(data).strip()
        if not text:
            self._trace(
                trace,
                "vision.search.result",
                {
                    "ok": False,
                    "error": "empty vision search response",
                    "response": data,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return VisionResult(ok=False, error="empty vision search response")
        self._trace(
            trace,
            "vision.search.result",
            {
                "ok": True,
                "summary": text,
                "response": data,
                "elapsed_ms": self._elapsed_ms(started),
            },
        )
        return VisionResult(ok=True, summary=text)

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.post(
                f"{self.api_base}{path}",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return data if isinstance(data, dict) else {}

    async def _image_input_urls(
        self,
        image_urls: list[str],
        *,
        trace: DebugTrace | None,
    ) -> list[str]:
        prepared: list[str] = []
        for url in image_urls:
            prepared.append(await self._image_data_url_or_original(url, trace=trace))
        return prepared

    async def _image_data_url_or_original(
        self,
        url: str,
        *,
        trace: DebugTrace | None,
    ) -> str:
        started = time.monotonic()
        try:
            content, content_type = await self._download_image(url)
        except Exception as exc:
            self._trace(
                trace,
                "vision.image.fetch.result",
                {
                    "ok": False,
                    "source_url": url,
                    "error": self._exception_text(exc),
                    "error_type": type(exc).__name__,
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return url

        if content_type is None:
            self._trace(
                trace,
                "vision.image.fetch.result",
                {
                    "ok": False,
                    "source_url": url,
                    "error": "downloaded content is not a supported image",
                    "bytes": len(content),
                    "elapsed_ms": self._elapsed_ms(started),
                },
            )
            return url

        data_url = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
        self._trace(
            trace,
            "vision.image.fetch.result",
            {
                "ok": True,
                "source_url": url,
                "content_type": content_type,
                "bytes": len(content),
                "elapsed_ms": self._elapsed_ms(started),
            },
        )
        return data_url

    async def _download_image(self, url: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
        return content, self._image_content_type(
            response.headers.get("Content-Type", ""),
            content,
        )

    @staticmethod
    def _http_urls(urls: list[str]) -> list[str]:
        return [url for url in urls if url.startswith(("http://", "https://"))]

    @staticmethod
    def _is_gif_url(url: str) -> bool:
        return urlparse(url).path.lower().endswith(".gif")

    @staticmethod
    def _response_text(data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text

        parts: list[str] = []
        output = data.get("output")
        if not isinstance(output, list):
            return ""
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                if content_item.get("type") == "output_text":
                    text = content_item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _image_content_type(header: str, content: bytes) -> str | None:
        content_type = header.split(";", 1)[0].strip().lower()
        if content_type.startswith("image/"):
            return content_type
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        return None

    @staticmethod
    def _exception_text(exc: Exception) -> str:
        text = str(exc).strip()
        return text or type(exc).__name__

    @classmethod
    def _trace(cls, trace: DebugTrace | None, name: str, data: dict[str, Any]) -> None:
        if trace is not None:
            trace.event(name, cls._redact_data_urls(data))

    @classmethod
    def _redact_data_urls(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._redact_data_urls(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._redact_data_urls(item) for item in value]
        if isinstance(value, str) and value.startswith("data:"):
            header, separator, encoded = value.partition(",")
            if not separator:
                return "data:<redacted>"
            return f"{header},<redacted {len(encoded)} chars>"
        return value

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return round((time.monotonic() - started) * 1000)
