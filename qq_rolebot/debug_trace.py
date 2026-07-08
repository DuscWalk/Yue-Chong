from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DebugTrace:
    trace_id: str
    path: Path
    logger: DebugTraceLogger

    def event(self, name: str, data: dict[str, Any]) -> None:
        self.logger.write_event(self, name, data)


class DebugTraceLogger:
    def __init__(
        self,
        *,
        root_dir: Path,
        retention_seconds: int = 86_400,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.root_dir = root_dir
        self.retention_seconds = retention_seconds
        self.now = now or time.time

    def start_trace(self, data: dict[str, Any]) -> DebugTrace:
        self._prune()
        timestamp = datetime.fromtimestamp(self.now(), UTC).strftime("%Y%m%dT%H%M%SZ")
        trace_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        trace = DebugTrace(
            trace_id=trace_id,
            path=self.root_dir / f"{trace_id}.jsonl",
            logger=self,
        )
        trace.event("message.received", data)
        return trace

    def write_event(self, trace: DebugTrace, name: str, data: dict[str, Any]) -> None:
        self._prune()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.fromtimestamp(self.now(), UTC).isoformat(),
            "trace_id": trace.trace_id,
            "event": name,
            "data": data,
        }
        with trace.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, default=str))
            file.write("\n")

    def _prune(self) -> None:
        if not self.root_dir.exists():
            return
        cutoff = self.now() - self.retention_seconds
        for path in self.root_dir.glob("*.jsonl"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                continue
