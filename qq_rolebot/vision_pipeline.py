from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qq_rolebot.debug_trace import DebugTrace
from qq_rolebot.vision_client import VisualAnalysis
from qq_rolebot.vision_types import (
    ConfidenceBand,
    LensEvidence,
    VisionObservation,
    VisionResolution,
)


@dataclass(frozen=True)
class VisionPipelineResult:
    ok: bool
    context_text: str
    resolutions: tuple[VisionResolution, ...] = ()
    timed_out: bool = False
    error: str = ""


class VisionPipeline:
    def __init__(
        self,
        *,
        preprocessor: Any,
        analyzer: Any,
        lens_client: Any,
        web_client: Any,
        temp_store: Any,
        resolver: Any,
        cache: Any,
        total_timeout_seconds: float,
        max_images: int,
        web_candidate_limit: int,
        cache_version: str,
        now: Callable[[], int] | None = None,
    ) -> None:
        self.preprocessor = preprocessor
        self.analyzer = analyzer
        self.lens_client = lens_client
        self.web_client = web_client
        self.temp_store = temp_store
        self.resolver = resolver
        self.cache = cache
        self.total_timeout_seconds = total_timeout_seconds
        self.max_images = max_images
        self.web_candidate_limit = web_candidate_limit
        self.cache_version = cache_version
        self.now = now or (lambda: int(time.time()))
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def describe(
        self,
        image_urls: list[str],
        video_urls: list[str] | None = None,
        *,
        user_question: str,
        chat_context: str,
        trace: DebugTrace | None = None,
    ) -> VisionPipelineResult:
        selected_images = [
            url for url in image_urls if url.startswith(("http://", "https://"))
        ][: self.max_images]
        selected_videos = [
            url for url in (video_urls or []) if url.startswith(("http://", "https://"))
        ][: self.max_images]
        if not selected_images and not selected_videos:
            return VisionPipelineResult(ok=False, context_text="", error="no media urls")

        started = time.monotonic()
        deadline = started + self.total_timeout_seconds
        image_tasks = [
            asyncio.create_task(
                self._process_image(
                    url,
                    user_question=user_question,
                    chat_context=chat_context,
                    deadline=deadline,
                    trace=trace,
                )
            )
            for url in selected_images
        ]
        dynamic_task = (
            asyncio.create_task(
                self.analyzer.describe_dynamic_media(
                    selected_videos,
                    user_question=user_question,
                    trace=trace,
                    timeout_seconds=self._remaining(deadline),
                )
            )
            if selected_videos
            else None
        )
        timed_out = False
        resolutions: tuple[VisionResolution, ...] = ()
        dynamic_observation = VisionObservation()
        try:
            async with asyncio.timeout(self.total_timeout_seconds):
                if image_tasks:
                    resolutions = tuple(await asyncio.gather(*image_tasks))
                if dynamic_task is not None:
                    dynamic_observation = await dynamic_task
        except TimeoutError:
            timed_out = True
            for task in image_tasks:
                task.cancel()
            if dynamic_task is not None:
                dynamic_task.cancel()
            await asyncio.gather(*image_tasks, return_exceptions=True)
            if dynamic_task is not None:
                await asyncio.gather(dynamic_task, return_exceptions=True)
            ordered: list[VisionResolution] = []
            for task in image_tasks:
                if task.done() and not task.cancelled() and task.exception() is None:
                    ordered.append(task.result())
                else:
                    ordered.append(
                        VisionResolution.uncertain(
                            observation=VisionObservation(),
                            reason="识图总预算已用尽",
                        )
                    )
            resolutions = tuple(ordered)
        except Exception as exc:
            for task in image_tasks:
                task.cancel()
            if dynamic_task is not None:
                dynamic_task.cancel()
            await asyncio.gather(*image_tasks, return_exceptions=True)
            if dynamic_task is not None:
                await asyncio.gather(dynamic_task, return_exceptions=True)
            resolutions = tuple(
                VisionResolution.unavailable(
                    observation=VisionObservation(),
                    reason=self._exception_text(exc),
                )
                for _ in selected_images
            )

        context_parts = [
            resolution.to_context_text(image_number=index)
            for index, resolution in enumerate(resolutions, start=1)
        ]
        if selected_videos:
            description = dynamic_observation.scene_description or "无法可靠描述动态媒体。"
            context_parts.append(
                "动态媒体：\n"
                f"视觉观察：{description}\n"
                "身份判断：动态媒体首版只提供客观描述，不确认具体身份。"
            )
        context_text = "\n\n".join(context_parts)
        if trace is not None:
            trace.event(
                "vision.pipeline.result",
                {
                    "ok": bool(context_text),
                    "timed_out": timed_out,
                    "image_count": len(resolutions),
                    "video_count": len(selected_videos),
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "confirmed_count": sum(
                        item.confidence is ConfidenceBand.CONFIRMED for item in resolutions
                    ),
                },
            )
        return VisionPipelineResult(
            ok=bool(context_text),
            context_text=context_text,
            resolutions=resolutions,
            timed_out=timed_out,
        )

    async def close(self) -> None:
        if self._cleanup_tasks:
            await asyncio.gather(*tuple(self._cleanup_tasks), return_exceptions=True)

    async def _process_image(
        self,
        url: str,
        *,
        user_question: str,
        chat_context: str,
        deadline: float,
        trace: DebugTrace | None,
    ) -> VisionResolution:
        image = await self.preprocessor.fetch(
            url,
            trace=trace,
            timeout_seconds=self._remaining(deadline),
        )
        cached = await self.cache.get_resolution(
            image.sha256,
            version=self.cache_version,
            now=self.now(),
        )
        if cached is not None:
            if trace is not None:
                trace.event("vision.cache.hit", {"stage": "resolution"})
            return cached

        cached_observation, cached_lens = await asyncio.gather(
            self.cache.get_observation(
                image.sha256,
                version=self.cache_version,
                now=self.now(),
            ),
            self.cache.get_lens(
                image.sha256,
                version=self.cache_version,
                now=self.now(),
            ),
        )
        visual_task = (
            asyncio.create_task(
                self.analyzer.analyze_image(
                    image,
                    user_question=user_question,
                    chat_context=chat_context,
                    trace=trace,
                    timeout_seconds=self._remaining(deadline),
                )
            )
            if cached_observation is None
            else None
        )
        publish_task = (
            asyncio.create_task(self.temp_store.publish(image, trace=trace))
            if cached_lens is None
            else None
        )
        lens_task = (
            asyncio.create_task(
                self.lens_client.search(
                    url,
                    trace=trace,
                    timeout_seconds=self._remaining(deadline),
                )
            )
            if cached_lens is None
            else None
        )
        handle = None
        publication_detached = False
        try:
            if visual_task is not None:
                visual = await visual_task
                if not visual.error:
                    await self.cache.put_observation(
                        image.sha256,
                        version=self.cache_version,
                        observation=visual.observation,
                        now=self.now(),
                    )
            else:
                visual = VisualAnalysis(observation=cached_observation or VisionObservation())

            if lens_task is None:
                lens = cached_lens or LensEvidence()
            else:
                lens_result = await lens_task
                if lens_result.ok:
                    lens = lens_result.evidence
                    if publish_task is not None:
                        self._schedule_publication_cleanup(publish_task)
                        publication_detached = True
                elif lens_result.unreachable and self._remaining(deadline) > 0:
                    if publish_task is None:
                        lens = LensEvidence()
                    else:
                        handle = await publish_task
                        retry = await self.lens_client.search(
                            handle.url,
                            trace=trace,
                            timeout_seconds=self._remaining(deadline),
                        )
                        lens = retry.evidence if retry.ok else LensEvidence()
                else:
                    lens = LensEvidence()
                    if publish_task is not None:
                        self._schedule_publication_cleanup(publish_task)
                        publication_detached = True
                if lens.exact_matches or lens.visual_matches:
                    await self.cache.put_lens(
                        image.sha256,
                        version=self.cache_version,
                        lens=lens,
                        now=self.now(),
                    )

            lens_candidates = await self.analyzer.extract_search_candidates(
                lens,
                observation=visual.observation,
                user_question=user_question,
                trace=trace,
                timeout_seconds=self._remaining(deadline),
            )
            candidates = (*visual.candidates, *lens_candidates)
            selected = self.resolver.select_web_candidates(
                tuple(candidates),
                lens,
                limit=self.web_candidate_limit,
            )
            web_evidence = ()
            if selected and self._remaining(deadline) > 0:
                web_evidence = tuple(
                    await asyncio.gather(
                        *[
                            self.web_client.verify(
                                candidate,
                                visual_features=visual.observation.distinctive_features,
                                trace=trace,
                                timeout_seconds=self._remaining(deadline),
                            )
                            for candidate in selected
                        ]
                    )
                )
            decision = self.resolver.resolve(
                observation=visual.observation,
                visual_candidates=tuple(candidates),
                lens=lens,
                web_evidence=web_evidence,
            )
            await self.cache.put_resolution(
                image.sha256,
                version=self.cache_version,
                resolution=decision.resolution,
                now=self.now(),
            )
            if trace is not None:
                trace.event(
                    "vision.resolver.result",
                    {
                        "rule_id": decision.rule_id,
                        "confidence": decision.resolution.confidence.value,
                    },
                )
            return decision.resolution
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            observation = VisionObservation()
            if visual_task is not None and visual_task.done() and not visual_task.cancelled():
                try:
                    observation = visual_task.result().observation
                except Exception:
                    pass
            return VisionResolution.unavailable(
                observation=observation,
                reason=self._exception_text(exc),
            )
        finally:
            if (
                publish_task is not None
                and not publication_detached
                and handle is None
                and publish_task.done()
                and not publish_task.cancelled()
            ):
                try:
                    handle = publish_task.result()
                except Exception:
                    handle = None
            if (
                publish_task is not None
                and not publication_detached
                and not publish_task.done()
            ):
                publish_task.cancel()
                await asyncio.gather(publish_task, return_exceptions=True)
            if handle is not None:
                self._schedule_cleanup(handle)
            for task in (visual_task, lens_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (visual_task, lens_task) if task is not None),
                return_exceptions=True,
            )

    def _schedule_cleanup(self, handle: Any) -> None:
        task = asyncio.create_task(self._delete_handle(handle))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def _schedule_publication_cleanup(self, publish_task: asyncio.Task[Any]) -> None:
        task = asyncio.create_task(self._finish_publication_cleanup(publish_task))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    @classmethod
    async def _finish_publication_cleanup(cls, publish_task: asyncio.Task[Any]) -> None:
        try:
            handle = await publish_task
        except Exception:
            return
        await cls._delete_handle(handle)

    @staticmethod
    async def _delete_handle(handle: Any) -> None:
        try:
            await asyncio.shield(handle.delete())
        except Exception:
            return

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.001, deadline - time.monotonic())

    @staticmethod
    def _exception_text(exc: Exception) -> str:
        return str(exc).strip() or type(exc).__name__
