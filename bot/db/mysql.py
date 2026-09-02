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
        self._init_schema()

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

    def add_subscriber(self, chat_id: str, username: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO subscribers (chat_id, username, active)
                   VALUES (%s, %s, 1)
                   ON DUPLICATE KEY UPDATE active = 1""",
                (chat_id, username),
            )
        self._conn.commit()

    def remove_subscriber(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET active = 0 WHERE chat_id = %s",
                (chat_id,),
            )
        self._conn.commit()

    def list_active_subscribers(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM subscribers WHERE active = 1")
            return [row["chat_id"] for row in cur.fetchall()]

    def get_last_update_id(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT value FROM bot_state WHERE `key` = 'last_update_id'")
            row = cur.fetchone()
        return int(row["value"]) if row else 0

    def set_last_update_id(self, update_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bot_state (`key`, value) VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE value = VALUES(value)""",
                ("last_update_id", str(update_id)),
            )
        self._conn.commit()

    def _init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chat_id VARCHAR(255) NOT NULL UNIQUE,
                    username VARCHAR(255),
                    active INT NOT NULL DEFAULT 1,
                    plan VARCHAR(50) NOT NULL DEFAULT 'free',
                    subscribed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    `key` VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
