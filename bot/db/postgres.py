import psycopg2
import psycopg2.extras
from bot.db.base import DatabaseDriver


class PostgresDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False

    def get_pending(self, limit: int) -> list[dict]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM messages WHERE queue_sent = 0 AND read = 0 LIMIT %s",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def mark_sent(self, ids: list[int]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE messages SET queue_sent = 1 WHERE id = ANY(%s)",
                (ids,),
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
