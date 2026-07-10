from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

import boto3

from qq_rolebot.debug_trace import DebugTrace
from qq_rolebot.image_preprocessor import NormalizedImage


class TemporaryImageStoreError(RuntimeError):
    pass


class TemporaryImageHandle(Protocol):
    url: str
    object_key: str

    async def delete(self) -> None: ...


class TemporaryImageStore(Protocol):
    async def publish(
        self,
        image: NormalizedImage,
        *,
        trace: DebugTrace | None = None,
    ) -> TemporaryImageHandle: ...


@dataclass
class R2TemporaryImageHandle:
    url: str
    object_key: str
    bucket: str
    s3_client: Any
    trace: DebugTrace | None = None
    _deleted: bool = field(default=False, init=False, repr=False)
    _delete_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def delete(self) -> None:
        async with self._delete_lock:
            if self._deleted:
                return
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.bucket,
                Key=self.object_key,
            )
            self._deleted = True
            if self.trace is not None:
                self.trace.event(
                    "vision.temp_store.delete",
                    {"ok": True, "bucket": self.bucket, "object_key": self.object_key},
                )


class R2TemporaryImageStore:
    def __init__(
        self,
        *,
        bucket: str,
        object_prefix: str,
        presigned_url_seconds: int,
        account_id: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        s3_client: Any | None = None,
    ) -> None:
        self.bucket = bucket
        self.object_prefix = object_prefix.rstrip("/") + "/"
        self.presigned_url_seconds = presigned_url_seconds
        self.s3_client = s3_client or boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def publish(
        self,
        image: NormalizedImage,
        *,
        trace: DebugTrace | None = None,
    ) -> R2TemporaryImageHandle:
        extension = ".jpg" if image.content_type == "image/jpeg" else ".png"
        object_key = f"{self.object_prefix}{secrets.token_urlsafe(24)}{extension}"
        try:
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.bucket,
                Key=object_key,
                Body=image.content,
                ContentType=image.content_type,
                CacheControl="private, max-age=300",
            )
            url = await asyncio.to_thread(
                self.s3_client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=self.presigned_url_seconds,
            )
        except Exception as exc:
            try:
                await asyncio.to_thread(
                    self.s3_client.delete_object,
                    Bucket=self.bucket,
                    Key=object_key,
                )
            except Exception:
                pass
            if trace is not None:
                trace.event(
                    "vision.temp_store.publish",
                    {
                        "ok": False,
                        "bucket": self.bucket,
                        "object_key": object_key,
                        "error": self._exception_text(exc),
                    },
                )
            raise TemporaryImageStoreError(self._exception_text(exc)) from exc
        if trace is not None:
            trace.event(
                "vision.temp_store.publish",
                {
                    "ok": True,
                    "bucket": self.bucket,
                    "object_key": object_key,
                    "content_type": image.content_type,
                    "bytes": len(image.content),
                },
            )
        return R2TemporaryImageHandle(
            url=str(url),
            object_key=object_key,
            bucket=self.bucket,
            s3_client=self.s3_client,
            trace=trace,
        )

    @staticmethod
    def _exception_text(exc: Exception) -> str:
        return str(exc).strip() or type(exc).__name__
