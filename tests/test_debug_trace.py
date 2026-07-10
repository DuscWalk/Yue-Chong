import json
import os
from pathlib import Path

from qq_rolebot.debug_trace import DebugTraceLogger


def read_events(path: Path) -> list[dict]:
    files = list(path.glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_debug_trace_logger_writes_full_events_and_prunes_old_files(tmp_path: Path) -> None:
    old = tmp_path / "old.jsonl"
    old.write_text('{"event":"old"}\n', encoding="utf-8")
    os.utime(old, (99_000, 99_000))
    logger = DebugTraceLogger(
        root_dir=tmp_path,
        retention_seconds=86_400,
        now=lambda: 200_000,
    )

    trace = logger.start_trace(
        {
            "text": "这是哪个",
            "media_urls": ["https://example.test/private-image.png"],
        }
    )
    trace.event(
        "model.prompt",
        {"messages": [{"role": "user", "content": "完整 prompt"}]},
    )

    assert not old.exists()
    events = read_events(tmp_path)
    assert events[0]["event"] == "message.received"
    assert events[0]["data"]["media_urls"] == ["https://example.test/private-image.png"]
    assert events[1]["event"] == "model.prompt"
    assert events[1]["data"]["messages"][0]["content"] == "完整 prompt"
    assert events[1]["trace_id"] == events[0]["trace_id"]


def test_debug_trace_logger_redacts_url_query_strings_in_nested_text(tmp_path: Path) -> None:
    logger = DebugTraceLogger(root_dir=tmp_path, now=lambda: 200_000)

    trace = logger.start_trace(
        {
            "text": "看看 https://qq.test/image?token=private&file=secret#fragment",
            "nested": [{"url": "https://signed.test/object?sig=secret"}],
        }
    )

    raw = trace.path.read_text(encoding="utf-8")
    assert "https://qq.test/image" in raw
    assert "https://signed.test/object" in raw
    assert "token=private" not in raw
    assert "file=secret" not in raw
    assert "sig=secret" not in raw
