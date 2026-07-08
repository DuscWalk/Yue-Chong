from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class GroupSettings:
    group_id: int
    enabled: bool
    random_probability: int
    muted_until: int


@dataclass(frozen=True)
class MessageRecord:
    group_id: int
    user_id: int
    nickname: str
    text: str
    created_at: int


class Storage:
    def __init__(
        self,
        path: Path,
        context_limit: int = 20,
        default_probability: int = 8,
        context_window_seconds: int = 600,
    ) -> None:
        self.path = path
        self.context_limit = context_limit
        self.default_probability = default_probability
        self.context_window_seconds = context_window_seconds

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    random_probability INTEGER NOT NULL,
                    muted_until INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS message_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_message_context_group_time
                ON message_context(group_id, created_at);

                CREATE TABLE IF NOT EXISTS user_notes (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );
                """
            )
            await db.commit()

    async def get_group_settings(self, group_id: int) -> GroupSettings:
        async with aiosqlite.connect(self.path) as db:
            row = await db.execute_fetchall(
                """
                SELECT group_id, enabled, random_probability, muted_until
                FROM group_settings
                WHERE group_id = ?
                """,
                (group_id,),
            )
            if not row:
                return GroupSettings(
                    group_id=group_id,
                    enabled=False,
                    random_probability=self.default_probability,
                    muted_until=0,
                )
            item = row[0]
            return GroupSettings(
                group_id=int(item[0]),
                enabled=bool(item[1]),
                random_probability=int(item[2]),
                muted_until=int(item[3]),
            )

    async def _ensure_group(self, db: aiosqlite.Connection, group_id: int) -> None:
        await db.execute(
            """
            INSERT OR IGNORE INTO group_settings
                (group_id, enabled, random_probability, muted_until)
            VALUES (?, 0, ?, 0)
            """,
            (group_id, self.default_probability),
        )

    async def set_group_enabled(self, group_id: int, enabled: bool) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET enabled = ? WHERE group_id = ?",
                (1 if enabled else 0, group_id),
            )
            await db.commit()

    async def set_random_probability(self, group_id: int, probability: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET random_probability = ? WHERE group_id = ?",
                (probability, group_id),
            )
            await db.commit()

    async def set_muted_until(self, group_id: int, muted_until: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await self._ensure_group(db, group_id)
            await db.execute(
                "UPDATE group_settings SET muted_until = ? WHERE group_id = ?",
                (muted_until, group_id),
            )
            await db.commit()

    async def save_message(self, record: MessageRecord) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO message_context (group_id, user_id, nickname, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record.group_id, record.user_id, record.nickname, record.text, record.created_at),
            )
            await db.execute(
                """
                DELETE FROM message_context
                WHERE group_id = ?
                  AND id NOT IN (
                    SELECT id FROM message_context
                    WHERE group_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                  )
                """,
                (record.group_id, record.group_id, self.context_limit),
            )
            await db.commit()

    async def recent_messages(
        self,
        group_id: int,
        *,
        now: int | None = None,
    ) -> list[MessageRecord]:
        cutoff = None if now is None else now - self.context_window_seconds
        async with aiosqlite.connect(self.path) as db:
            if cutoff is None:
                rows = await db.execute_fetchall(
                    """
                    SELECT group_id, user_id, nickname, text, created_at
                    FROM message_context
                    WHERE group_id = ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (group_id,),
                )
            else:
                rows = await db.execute_fetchall(
                    """
                    SELECT group_id, user_id, nickname, text, created_at
                    FROM message_context
                    WHERE group_id = ?
                      AND created_at >= ?
                      AND created_at <= ?
                    ORDER BY created_at ASC, id ASC
                    """,
                    (group_id, cutoff, now),
                )
            return [
                MessageRecord(
                    group_id=int(row[0]),
                    user_id=int(row[1]),
                    nickname=str(row[2]),
                    text=str(row[3]),
                    created_at=int(row[4]),
                )
                for row in rows
            ]

    async def clear_context(self, group_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM message_context WHERE group_id = ?", (group_id,))
            await db.commit()
