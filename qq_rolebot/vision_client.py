from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


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
        self.transport = transport

    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
    ) -> VisionResult:
        images = self._http_urls(image_urls)[: self.max_images]
        videos = self._http_urls(video_urls or [])[: self.max_images]
        if not images and not videos:
            return VisionResult(ok=False, error="no media urls")

        summaries: list[str] = []
        errors: list[str] = []

        media = await self._describe_media(images, videos)
        if media.ok and media.summary:
            summaries.append(media.summary)
        elif media.error:
            errors.append(media.error)

        search = await self._search_images(images, videos)
        if search.ok and search.summary:
            summaries.append(search.summary)
        elif search.error:
            errors.append(search.error)

        if summaries:
            return VisionResult(ok=True, summary="\n".join(summaries))
        return VisionResult(ok=False, error="; ".join(errors) or "empty vision response")

    async def _describe_media(self, image_urls: list[str], video_urls: list[str]) -> VisionResult:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    "请用简体中文客观概括这些聊天图片、表情包、动图或视频。"
                    "只描述可见内容、文字、动作和情绪，不要扮演角色，不要编造。"
                    "看不清或无法识别时请明确说不确定。100字以内。"
                ),
            }
        ]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls)
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

        try:
            data = await self._post_json("/chat/completions", payload)
        except Exception as exc:
            return VisionResult(ok=False, error=str(exc))

        try:
            summary = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return VisionResult(ok=False, error=f"invalid vision response: {exc}")

        text = str(summary).strip()
        if not text:
            return VisionResult(ok=False, error="empty vision response")
        return VisionResult(ok=True, summary=text)

    async def _search_images(
        self,
        image_urls: list[str],
        video_urls: list[str],
    ) -> VisionResult:
        if not self.enable_search:
            return VisionResult(ok=False, error="vision search disabled")

        search_urls = [*image_urls, *[url for url in video_urls if self._is_gif_url(url)]]
        search_urls = search_urls[: self.max_images]
        if not search_urls:
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

        try:
            data = await self._post_json("/responses", payload)
        except Exception as exc:
            return VisionResult(ok=False, error=str(exc))

        text = self._response_text(data).strip()
        if not text:
            return VisionResult(ok=False, error="empty vision search response")
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
