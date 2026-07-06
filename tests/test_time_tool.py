from datetime import datetime
from zoneinfo import ZoneInfo

from qq_rolebot.time_tool import TimeTool


def test_time_tool_formats_shanghai_time() -> None:
    tool = TimeTool(timezone="Asia/Shanghai")
    now = datetime(2026, 7, 6, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    reply = tool.reply(now=now)

    assert reply.startswith("当前时间：")
    assert "2026-07-06" in reply
    assert "09:30" in reply
    assert "Asia/Shanghai" in reply
