from urllib.parse import urlparse
import pymysql
import pymysql.cursors
from bot.db.base import DatabaseDriver


class MySQLDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        parsed = urlparse(dsn)
        self._conn = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    def get_pending(self, limit: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM messages WHERE queue_sent = 0 AND `read` = 0 LIMIT %s",
                (limit,),
            )
            return cur.fetchall()

    def mark_sent(self, ids: list[int]) -> None:
        placeholders = ",".join(["%s"] * len(ids))
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE messages SET queue_sent = 1 WHERE id IN ({placeholders})",
                ids,
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
