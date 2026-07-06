from __future__ import annotations

from qq_rolebot.config import Settings
from qq_rolebot.storage import Storage


def is_admin_command(text: str) -> bool:
    return text.strip().startswith("/bot")


def parse_duration_seconds(raw: str) -> int:
    value = raw.strip().lower()
    if len(value) < 2:
        raise ValueError("duration must include a unit")
    amount = int(value[:-1])
    unit = value[-1]
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    raise ValueError("duration unit must be s, m, or h")


async def handle_admin_command(
    text: str,
    *,
    sender_id: int,
    group_id: int,
    now: int,
    settings: Settings,
    storage: Storage,
) -> str | None:
    if sender_id not in settings.admin_users:
        return None

    parts = text.strip().split()
    if len(parts) < 2 or parts[0] != "/bot":
        return "usage: /bot on|off|mute|prob|clear|status|persona"

    command = parts[1].lower()
    if command == "on":
        await storage.set_group_enabled(group_id, True)
        return "bot enabled"
    if command == "off":
        await storage.set_group_enabled(group_id, False)
        return "bot disabled"
    if command == "mute":
        if len(parts) != 3:
            return "usage: /bot mute 10m"
        seconds = parse_duration_seconds(parts[2])
        await storage.set_muted_until(group_id, now + seconds)
        return f"bot muted for {parts[2]}"
    if command == "prob":
        if len(parts) != 3:
            return "usage: /bot prob 8"
        probability = int(parts[2])
        if probability < 0 or probability > 100:
            return "probability must be between 0 and 100"
        await storage.set_random_probability(group_id, probability)
        return f"random reply probability set to {probability}%"
    if command == "clear":
        await storage.clear_context(group_id)
        return "context cleared"
    if command == "status":
        group = await storage.get_group_settings(group_id)
        return (
            f"enabled={group.enabled}, "
            f"random_probability={group.random_probability}%, "
            f"muted_until={group.muted_until}"
        )
    return "usage: /bot on|off|mute|prob|clear|status|persona"
