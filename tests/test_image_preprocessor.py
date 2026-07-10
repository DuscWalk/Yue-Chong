from __future__ import annotations

import io

import httpx
import pytest
from PIL import Image

from qq_rolebot.image_preprocessor import ImagePreprocessError, ImagePreprocessor


def image_bytes(
    *,
    image_format: str = "PNG",
    width: int = 32,
    height: int = 16,
    frames: int = 1,
) -> bytes:
    output = io.BytesIO()
    images = [
        Image.new("RGB", (width, height), color=(index * 40, 20, 30))
        for index in range(frames)
    ]
    images[0].save(
        output,
        format=image_format,
        save_all=frames > 1,
        append_images=images[1:],
        loop=0,
    )
    return output.getvalue()


def transport_returning(content: bytes, *, content_type: str = "image/png") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"Content-Type": content_type})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_preprocessor_normalizes_and_hashes_image() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        transport=transport_returning(image_bytes()),
    )

    image = await preprocessor.fetch("https://qq.test/image?id=secret#fragment")

    assert image.content_type == "image/png"
    assert image.width == 32
    assert image.height == 16
    assert len(image.sha256) == 64
    assert image.source_url == "https://qq.test/image"
    assert image.data_url().startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_preprocessor_rejects_oversized_download() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=20,
        max_image_pixels=1_000_000,
        transport=transport_returning(image_bytes()),
    )

    with pytest.raises(ImagePreprocessError, match="download exceeds"):
        await preprocessor.fetch("https://qq.test/large")


@pytest.mark.asyncio
async def test_preprocessor_rejects_pixel_limit() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=100,
        transport=transport_returning(image_bytes(width=20, height=20)),
    )

    with pytest.raises(ImagePreprocessError, match="pixel limit"):
        await preprocessor.fetch("https://qq.test/huge.png")


@pytest.mark.asyncio
async def test_preprocessor_rejects_invalid_content() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024,
        max_image_pixels=1000,
        transport=transport_returning(b"not an image", content_type="text/plain"),
    )

    with pytest.raises(ImagePreprocessError, match="invalid image"):
        await preprocessor.fetch("https://qq.test/not-image")


@pytest.mark.asyncio
async def test_preprocessor_rejects_animated_image_from_static_path() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1000,
        transport=transport_returning(
            image_bytes(image_format="GIF", frames=2),
            content_type="image/gif",
        ),
    )

    with pytest.raises(ImagePreprocessError, match="animated image"):
        await preprocessor.fetch("https://qq.test/animated.gif")


@pytest.mark.asyncio
async def test_preprocessor_converts_jpeg_to_safe_normalized_bytes() -> None:
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1000,
        transport=transport_returning(
            image_bytes(image_format="JPEG"),
            content_type="application/octet-stream",
        ),
    )

    image = await preprocessor.fetch("https://qq.test/photo")

    assert image.content_type == "image/jpeg"
    assert image.content.startswith(b"\xff\xd8\xff")
