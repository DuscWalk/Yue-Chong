from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


class TimeTool:
    def __init__(self, *, timezone: str = "Asia/Shanghai") -> None:
        self.timezone = timezone

    def reply(self, *, now: datetime | None = None) -> str:
        zone = ZoneInfo(self.timezone)
        current = now.astimezone(zone) if now is not None else datetime.now(zone)
        return f"当前时间：{current:%Y-%m-%d %H:%M:%S}（{self.timezone}）。"
