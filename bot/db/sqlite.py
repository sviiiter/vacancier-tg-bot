import sqlite3
from bot.db.base import DatabaseDriver


class SQLiteDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = sqlite3.connect(dsn, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def get_pending(self, limit: int) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM messages WHERE queue_sent = 0 AND read = 0 LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def mark_sent(self, ids: list[int]) -> None:
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"UPDATE messages SET queue_sent = 1 WHERE id IN ({placeholders})",
            ids,
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
