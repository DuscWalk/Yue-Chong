import pytest

from qq_rolebot.policy import IncomingMessage
from qq_rolebot.time_tool import TimeTool
from qq_rolebot.tool_router import ToolRouter
from qq_rolebot.tool_runner import ToolRunner


class FakeSearch:
    async def search(self, query: str, *, max_results: int):
        class Result:
            ok = True

            def format_context(self):
                return f"search context for {query}"

        return Result()


class FakePersonaSources:
    async def lookup(self, query: str):
        class Result:
            ok = True

            def format_context(self):
                return f"persona context for {query}"

        return Result()


def msg(text: str):
    return IncomingMessage(
        group_id=0,
        user_id=99,
        nickname="Amy",
        text=text,
        is_at_bot=False,
        is_private=True,
        created_at=100,
    )


@pytest.mark.asyncio
async def test_tool_runner_returns_direct_time_reply() -> None:
    runner = ToolRunner(
        router=ToolRouter(search_cooldown_seconds=20),
        time_tool=TimeTool(timezone="Asia/Shanghai"),
        search_client=FakeSearch(),
        persona_source_client=FakePersonaSources(),
        search_max_results=3,
        enable_time=True,
        enable_search=True,
        enable_persona_sources=True,
    )

    result = await runner.run(msg("\u73b0\u5728\u51e0\u70b9"))

    assert result.direct_reply
    assert "当前时间：" in result.direct_reply


@pytest.mark.asyncio
async def test_tool_runner_returns_search_context() -> None:
    runner = ToolRunner(
        router=ToolRouter(search_cooldown_seconds=20),
        time_tool=TimeTool(timezone="Asia/Shanghai"),
        search_client=FakeSearch(),
        persona_source_client=FakePersonaSources(),
        search_max_results=3,
        enable_time=True,
        enable_search=True,
        enable_persona_sources=True,
    )

    result = await runner.run(msg("\u4eca\u5929\u65b0\u95fb"))

    assert result.direct_reply is None
    assert "search context" in result.context
