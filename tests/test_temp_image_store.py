from __future__ import annotations

import pytest

from qq_rolebot.debug_trace import DebugTraceLogger
from qq_rolebot.image_preprocessor import NormalizedImage
from qq_rolebot.temp_image_store import R2TemporaryImageStore, TemporaryImageStoreError


class FakeS3Client:
    def __init__(self, *, fail_sign: bool = False) -> None:
        self.fail_sign = fail_sign
        self.put_calls: list[dict] = []
        self.delete_calls: list[tuple[str, str]] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)

    def generate_presigned_url(self, operation_name, *, Params, ExpiresIn):
        if self.fail_sign:
            raise RuntimeError("sign failed")
        assert operation_name == "get_object"
        assert ExpiresIn == 300
        return f"https://signed.test/{Params['Key']}?token=private"

    def delete_object(self, *, Bucket, Key):
        self.delete_calls.append((Bucket, Key))


def normalized_image() -> NormalizedImage:
    return NormalizedImage(
        content=b"png-bytes",
        content_type="image/png",
        width=10,
        height=10,
        sha256="a" * 64,
        source_url="https://qq.test/original-name.png",
    )


@pytest.mark.asyncio
async def test_r2_store_uploads_signs_and_deletes() -> None:
    s3 = FakeS3Client()
    store = R2TemporaryImageStore(
        bucket="private-vision",
        object_prefix="vision-temp/",
        presigned_url_seconds=300,
        s3_client=s3,
    )

    handle = await store.publish(normalized_image())
    await handle.delete()
    await handle.delete()

    assert s3.put_calls[0]["Bucket"] == "private-vision"
    assert s3.put_calls[0]["ContentType"] == "image/png"
    assert s3.put_calls[0]["Body"] == b"png-bytes"
    assert handle.url.startswith("https://signed.test/")
    assert handle.object_key.startswith("vision-temp/")
    assert handle.object_key.endswith(".png")
    assert "original-name" not in handle.object_key
    assert s3.delete_calls == [("private-vision", handle.object_key)]


@pytest.mark.asyncio
async def test_r2_store_deletes_uploaded_object_when_signing_fails() -> None:
    s3 = FakeS3Client(fail_sign=True)
    store = R2TemporaryImageStore(
        bucket="private-vision",
        object_prefix="vision-temp/",
        presigned_url_seconds=300,
        s3_client=s3,
    )

    with pytest.raises(TemporaryImageStoreError, match="sign failed"):
        await store.publish(normalized_image())

    key = s3.put_calls[0]["Key"]
    assert s3.delete_calls == [("private-vision", key)]


@pytest.mark.asyncio
async def test_r2_store_trace_never_contains_signed_url(tmp_path) -> None:
    s3 = FakeS3Client()
    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)
    trace = logger.start_trace({"text": "image"})
    store = R2TemporaryImageStore(
        bucket="private-vision",
        object_prefix="vision-temp/",
        presigned_url_seconds=300,
        s3_client=s3,
    )

    handle = await store.publish(normalized_image(), trace=trace)
    await handle.delete()

    raw = next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8")
    assert "vision.temp_store.publish" in raw
    assert "vision.temp_store.delete" in raw
    assert "https://signed.test" not in raw
    assert "token=private" not in raw
    assert "png-bytes" not in raw
