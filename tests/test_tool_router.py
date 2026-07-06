from qq_rolebot.policy import IncomingMessage
from qq_rolebot.tool_router import ToolKind, ToolRouter


def msg(text: str, *, private: bool = False, at: bool = False, reply: bool = False):
    return IncomingMessage(
        group_id=0 if private else 20,
        user_id=99,
        nickname="Amy",
        text=text,
        is_at_bot=at,
        is_private=private,
        is_reply_to_bot=reply,
        created_at=100,
    )


def test_private_today_news_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\u4eca\u5929\u65b0\u95fb", private=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_group_unaddressed_today_news_does_not_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\u4eca\u5929\u65b0\u95fb"), now=100)

    assert ToolKind.SEARCH not in plan.kinds


def test_group_mention_today_news_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\u4eca\u5929\u65b0\u95fb", at=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_group_reply_latest_weather_routes_to_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\u6700\u65b0\u5929\u6c14", reply=True), now=100)

    assert ToolKind.SEARCH in plan.kinds


def test_time_query_routes_to_time_not_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)

    plan = router.plan(msg("\u73b0\u5728\u51e0\u70b9", private=True), now=100)

    assert ToolKind.TIME in plan.kinds
    assert ToolKind.SEARCH not in plan.kinds


def test_role_question_routes_to_persona_source() -> None:
    router = ToolRouter(search_cooldown_seconds=20, persona_names=["Chongyue", "\u91cd\u5cb3"])

    plan = router.plan(msg("\u4f60\u7684\u6863\u6848", private=True), now=100)

    assert ToolKind.PERSONA_SOURCE in plan.kinds


def test_search_cooldown_blocks_repeated_open_search() -> None:
    router = ToolRouter(search_cooldown_seconds=20)
    first = router.plan(msg("\u4eca\u5929\u65b0\u95fb", private=True), now=100)
    router.record(msg("\u4eca\u5929\u65b0\u95fb", private=True), first, now=100)

    second = router.plan(msg("\u4eca\u5929\u65b0\u95fb", private=True), now=110)

    assert ToolKind.SEARCH not in second.kinds
