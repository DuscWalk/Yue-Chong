from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from qq_rolebot.debug_trace import DebugTrace


class ImagePreprocessError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedImage:
    content: bytes
    content_type: str
    width: int
    height: int
    sha256: str
    source_url: str

    def data_url(self) -> str:
        encoded = base64.b64encode(self.content).decode("ascii")
        return f"data:{self.content_type};base64,{encoded}"


class ImagePreprocessor:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_download_bytes: int,
        max_image_pixels: int,
        model_max_edge: int = 1600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.max_image_pixels = max_image_pixels
        self.model_max_edge = model_max_edge
        self.transport = transport

    async def fetch(
        self,
        url: str,
        *,
        trace: DebugTrace | None = None,
        timeout_seconds: float | None = None,
    ) -> NormalizedImage:
        source_url = self._redacted_url(url)
        content = await self._download(url, timeout_seconds=timeout_seconds)
        try:
            normalized = self._normalize(content, source_url=source_url)
        except (ImagePreprocessError, UnidentifiedImageError, OSError) as exc:
            error = (
                exc
                if isinstance(exc, ImagePreprocessError)
                else ImagePreprocessError("invalid image")
            )
            self._trace(
                trace,
                "vision.image.preprocess",
                {"ok": False, "url": source_url, "error": str(error)},
            )
            raise error from exc
        self._trace(
            trace,
            "vision.image.preprocess",
            {
                "ok": True,
                "url": source_url,
                "bytes": len(normalized.content),
                "width": normalized.width,
                "height": normalized.height,
                "content_type": normalized.content_type,
            },
        )
        return normalized

    async def _download(self, url: str, *, timeout_seconds: float | None) -> bytes:
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self.transport,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                parts: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_download_bytes:
                        raise ImagePreprocessError("download exceeds configured byte limit")
                    parts.append(chunk)
        return b"".join(parts)

    def _normalize(self, content: bytes, *, source_url: str) -> NormalizedImage:
        try:
            with Image.open(io.BytesIO(content)) as opened:
                if getattr(opened, "n_frames", 1) != 1:
                    raise ImagePreprocessError("animated image is not supported by static path")
                width, height = opened.size
                if width * height > self.max_image_pixels:
                    raise ImagePreprocessError("image exceeds configured pixel limit")
                image = ImageOps.exif_transpose(opened)
                image.load()
                if max(image.size) > self.model_max_edge:
                    image.thumbnail(
                        (self.model_max_edge, self.model_max_edge),
                        Image.Resampling.LANCZOS,
                    )
                output = io.BytesIO()
                if self._has_transparency(image):
                    if image.mode not in {"RGBA", "LA"}:
                        image = image.convert("RGBA")
                    image.save(output, format="PNG", optimize=True)
                    content_type = "image/png"
                else:
                    if image.mode not in {"RGB", "L"}:
                        image = image.convert("RGB")
                    image.save(output, format="JPEG", quality=88, optimize=True)
                    content_type = "image/jpeg"
                normalized = output.getvalue()
                return NormalizedImage(
                    content=normalized,
                    content_type=content_type,
                    width=image.width,
                    height=image.height,
                    sha256=hashlib.sha256(normalized).hexdigest(),
                    source_url=source_url,
                )
        except ImagePreprocessError:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise ImagePreprocessError("invalid image") from exc

    @staticmethod
    def _has_transparency(image: Image.Image) -> bool:
        if "transparency" in image.info:
            return True
        if "A" not in image.getbands():
            return False
        alpha_minimum, _ = image.getchannel("A").getextrema()
        return alpha_minimum < 255

    @staticmethod
    def _redacted_url(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    @staticmethod
    def _trace(trace: DebugTrace | None, name: str, data: dict[str, object]) -> None:
        if trace is not None:
            trace.event(name, data)
