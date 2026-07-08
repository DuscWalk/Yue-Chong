from __future__ import annotations

import re

LEAK_PREFIXES = (
    "system prompt",
    "developer message",
    "assistant instructions",
    "policy:",
    "stack trace",
    "traceback",
)

LEADING_ACTION_PATTERN = re.compile(r"^\s*[（(][^）)]{1,40}[）)]\s*")


def clean_response(
    text: str | None,
    *,
    max_chars: int,
    sensitive_words: list[str],
) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.strip().split())
    while True:
        stripped = LEADING_ACTION_PATTERN.sub("", cleaned, count=1).strip()
        if stripped == cleaned:
            break
        cleaned = stripped
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if any(lowered.startswith(prefix) for prefix in LEAK_PREFIXES):
        return None
    for word in sensitive_words:
        if word and word.lower() in lowered:
            return None
    return cleaned[:max_chars]
