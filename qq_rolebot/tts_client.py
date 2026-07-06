from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class TTSResult:
    ok: bool
    audio: bytes = b""
    extension: str = ".wav"
    error: str = ""


class TTSClient:
    def __init__(
        self,
        *,
        api_url: str,
        timeout_seconds: int,
        backend: str = "generic",
        ref_audio_path: str = "",
        prompt_text: str = "",
        prompt_lang: str = "zh",
        text_lang: str = "zh",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.backend = backend.strip().lower() or "generic"
        self.ref_audio_path = ref_audio_path
        self.prompt_text = prompt_text
        self.prompt_lang = prompt_lang
        self.text_lang = text_lang
        self.transport = transport

    async def synthesize(
        self,
        *,
        text: str,
        speaker: str,
        style: str,
        dialect_hint: str,
    ) -> TTSResult:
        if self.backend == "gptsovits":
            return await self._synthesize_gptsovits(text=text)
        return await self._synthesize_generic(
            text=text,
            speaker=speaker,
            style=style,
            dialect_hint=dialect_hint,
        )

    async def _synthesize_generic(
        self,
        *,
        text: str,
        speaker: str,
        style: str,
        dialect_hint: str,
    ) -> TTSResult:
        payload = {
            "text": text,
            "speaker": speaker,
            "style": style,
            "dialect_hint": dialect_hint,
            "format": "wav",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{self.api_url}/synthesize", json=payload)
            if response.status_code >= 400:
                return TTSResult(ok=False, error=f"TTS HTTP {response.status_code}")
            return self._parse_response(response)
        except Exception as exc:
            return TTSResult(ok=False, error=str(exc))

    async def _synthesize_gptsovits(self, *, text: str) -> TTSResult:
        payload = {
            "text": text,
            "text_lang": self.text_lang,
            "ref_audio_path": self.ref_audio_path,
            "prompt_text": self.prompt_text,
            "prompt_lang": self.prompt_lang,
            "media_type": "wav",
            "streaming_mode": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(f"{self.api_url}/tts", json=payload)
            if response.status_code >= 400:
                return TTSResult(ok=False, error=f"TTS HTTP {response.status_code}")
            return self._parse_response(response)
        except Exception as exc:
            return TTSResult(ok=False, error=str(exc))

    @staticmethod
    def _parse_response(response: httpx.Response) -> TTSResult:
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("audio/"):
            return TTSResult(
                ok=True,
                audio=response.content,
                extension=_audio_extension(content_type),
            )

        data = response.json()
        raw_audio = str(data.get("audio", ""))
        if not raw_audio:
            return TTSResult(ok=False, error="TTS response missing audio")
        extension = str(data.get("format", "wav")).strip().lower().lstrip(".")
        return TTSResult(
            ok=True,
            audio=base64.b64decode(raw_audio),
            extension=f".{extension or 'wav'}",
        )


def _audio_extension(content_type: str) -> str:
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    if "ogg" in content_type:
        return ".ogg"
    if "amr" in content_type:
        return ".amr"
    return ".wav"
