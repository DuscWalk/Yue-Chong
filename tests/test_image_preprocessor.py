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

    assert image.content_type == "image/jpeg"
    assert image.width == 32
    assert image.height == 16
    assert len(image.sha256) == 64
    assert image.source_url == "https://qq.test/image"
    assert image.data_url().startswith("data:image/jpeg;base64,")


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


@pytest.mark.asyncio
async def test_preprocessor_resizes_long_edge_without_enlarging_small_images() -> None:
    large = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=20 * 1024 * 1024,
        max_image_pixels=10_000_000,
        model_max_edge=1600,
        transport=transport_returning(image_bytes(width=2400, height=1200)),
    )
    small = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        model_max_edge=1600,
        transport=transport_returning(image_bytes(width=800, height=400)),
    )

    large_image = await large.fetch("https://qq.test/large.png")
    small_image = await small.fetch("https://qq.test/small.png")

    assert (large_image.width, large_image.height) == (1600, 800)
    assert (small_image.width, small_image.height) == (800, 400)


@pytest.mark.asyncio
async def test_preprocessor_applies_exif_orientation_before_resizing() -> None:
    output = io.BytesIO()
    source = Image.new("RGB", (80, 40), color=(10, 20, 30))
    exif = source.getexif()
    exif[274] = 6
    source.save(output, format="JPEG", exif=exif)
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        model_max_edge=60,
        transport=transport_returning(output.getvalue(), content_type="image/jpeg"),
    )

    image = await preprocessor.fetch("https://qq.test/oriented.jpg")

    assert (image.width, image.height) == (30, 60)


@pytest.mark.asyncio
async def test_preprocessor_compresses_large_opaque_png_for_four_image_payload() -> None:
    source = Image.effect_noise((1800, 1800), 80).convert("RGB")
    output = io.BytesIO()
    source.save(output, format="PNG")
    original = output.getvalue()
    preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=20 * 1024 * 1024,
        max_image_pixels=10_000_000,
        model_max_edge=1600,
        transport=transport_returning(original),
    )

    image = await preprocessor.fetch("https://qq.test/noise.png")

    assert image.content_type == "image/jpeg"
    assert len(image.content) * 4 < len(original) * 4
    assert len(image.content) < 2_000_000


@pytest.mark.asyncio
async def test_preprocessor_keeps_alpha_as_png_and_hashes_decoded_pixels_stably() -> None:
    transparent = Image.new("RGBA", (40, 20), color=(10, 20, 30, 120))
    first = io.BytesIO()
    second = io.BytesIO()
    transparent.save(first, format="PNG", optimize=False)
    transparent.save(second, format="PNG", optimize=True)

    alpha_preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        transport=transport_returning(first.getvalue()),
    )
    duplicate_preprocessor = ImagePreprocessor(
        timeout_seconds=2,
        max_download_bytes=1024 * 1024,
        max_image_pixels=1_000_000,
        transport=transport_returning(second.getvalue()),
    )

    first_image = await alpha_preprocessor.fetch("https://qq.test/alpha-a.png")
    second_image = await duplicate_preprocessor.fetch("https://qq.test/alpha-b.png")

    assert first_image.content_type == "image/png"
    assert Image.open(io.BytesIO(first_image.content)).mode == "RGBA"
    assert first_image.sha256 == second_image.sha256
