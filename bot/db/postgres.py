import psycopg2
import psycopg2.extras
from bot.db.base import DatabaseDriver


class PostgresDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._init_schema()

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

    def add_subscriber(self, chat_id: str, username: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO subscribers (chat_id, username, active)
                   VALUES (%s, %s, 1)
                   ON CONFLICT (chat_id) DO UPDATE SET active = 1""",
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
            return [row[0] for row in cur.fetchall()]

    def get_last_update_id(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT value FROM bot_state WHERE key = 'last_update_id'")
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def set_last_update_id(self, update_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO bot_state (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                ("last_update_id", str(update_id)),
            )
        self._conn.commit()

    def _init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL UNIQUE,
                    username TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    plan TEXT NOT NULL DEFAULT 'free',
                    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
