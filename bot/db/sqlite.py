import sqlite3
from bot.db.base import DatabaseDriver


class SQLiteDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = sqlite3.connect(dsn, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

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

    def add_subscriber(self, chat_id: str, username: str | None = None) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO subscribers (chat_id, username, active)
               VALUES (?, ?, 1)""",
            (chat_id, username),
        )
        self._conn.commit()

    def remove_subscriber(self, chat_id: str) -> None:
        self._conn.execute(
            "UPDATE subscribers SET active = 0 WHERE chat_id = ?",
            (chat_id,),
        )
        self._conn.commit()

    def list_active_subscribers(self) -> list[str]:
        cur = self._conn.execute("SELECT chat_id FROM subscribers WHERE active = 1")
        return [row[0] for row in cur.fetchall()]

    def get_last_update_id(self) -> int:
        cur = self._conn.execute("SELECT value FROM bot_state WHERE key = 'last_update_id'")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def set_last_update_id(self, update_id: int) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)""",
            ("last_update_id", str(update_id)),
        )
        self._conn.commit()

    def record_payment(self, chat_id: str, plan: str, amount: int, charge_id: str, is_recurring: int) -> bool:
        try:
            self._conn.execute(
                """INSERT INTO payments (chat_id, plan, amount, telegram_payment_charge_id, is_recurring)
                   VALUES (?, ?, ?, ?, ?)""",
                (chat_id, plan, amount, charge_id, is_recurring),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            self._conn.rollback()
            return False

    def activate_paid_plan(self, chat_id: str, plan: str, expires_at: str, charge_id: str | None = None) -> None:
        self._conn.execute(
            """UPDATE subscribers SET plan = ?, expires_at = ?, star_charge_id = ?, active = 1
               WHERE chat_id = ?""",
            (plan, expires_at, charge_id, chat_id),
        )
        self._conn.commit()

    def get_subscriber(self, chat_id: str) -> dict | None:
        cur = self._conn.execute("SELECT * FROM subscribers WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def downgrade_expired_subscribers(self) -> list[str]:
        cur = self._conn.execute(
            """UPDATE subscribers SET plan = 'free', expires_at = NULL, star_charge_id = NULL
               WHERE plan != 'free' AND expires_at < datetime('now')
               RETURNING chat_id"""
        )
        expired = [row[0] for row in cur.fetchall()]
        self._conn.commit()
        return expired

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL UNIQUE,
                username TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                plan TEXT NOT NULL DEFAULT 'free',
                subscribed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME,
                star_charge_id TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                plan TEXT NOT NULL,
                amount INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT 'stars',
                telegram_payment_charge_id TEXT UNIQUE,
                is_recurring INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
