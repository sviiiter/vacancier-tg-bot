import os
import sqlite3
from bot.db.base import DatabaseDriver


class SQLiteDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = sqlite3.connect(dsn, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def get_messages_by_ids(self, ids: list[int]) -> list[dict]:
        placeholders = ",".join("?" * len(ids))
        cur = self._conn.execute(
            f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY created_date ASC",
            ids,
        )
        return [dict(row) for row in cur.fetchall()]

    def update_message_sent_last_date(self, chat_id: str, ts) -> None:
        self._conn.execute(
            "UPDATE subscribers SET message_sent_last_date = ? WHERE chat_id = ? AND (message_sent_last_date IS NULL OR message_sent_last_date < ?)",
            (ts, chat_id, ts),
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

    def increment_messages_received(self, chat_ids: list[str]) -> None:
        if not chat_ids:
            return
        placeholders = ",".join("?" * len(chat_ids))
        self._conn.execute(
            f"UPDATE subscribers SET messages_received = messages_received + 1 WHERE chat_id IN ({placeholders})",
            chat_ids,
        )
        self._conn.commit()

    def mark_trial_notice_sent(self, chat_id: str) -> None:
        self._conn.execute(
            "UPDATE subscribers SET trial_notice_sent = 1 WHERE chat_id = ?",
            (chat_id,),
        )
        self._conn.commit()

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
                star_charge_id TEXT,
                messages_received INTEGER NOT NULL DEFAULT 0,
                trial_notice_sent INTEGER NOT NULL DEFAULT 0
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
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INTEGER PRIMARY KEY,
                stars_price_monthly INTEGER NOT NULL DEFAULT 100,
                stars_price_yearly INTEGER NOT NULL DEFAULT 1000,
                trial_type TEXT NOT NULL DEFAULT 'messages',
                trial_message_limit INTEGER NOT NULL DEFAULT 10,
                trial_days INTEGER NOT NULL DEFAULT 2
            )
        """)
        stars_price_monthly = int(os.getenv("STARS_PRICE_MONTHLY", "100"))
        stars_price_yearly = int(os.getenv("STARS_PRICE_YEARLY", "1000"))
        trial_type = os.getenv("TRIAL_TYPE", "messages")
        trial_message_limit = int(os.getenv("TRIAL_MESSAGE_LIMIT", "10"))
        trial_days = int(os.getenv("TRIAL_DAYS", "2"))
        self._conn.execute(
            """INSERT OR IGNORE INTO bot_settings (id, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (1, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days),
        )
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(subscribers)").fetchall()}
        for column, definition in [
            ("expires_at", "DATETIME"),
            ("star_charge_id", "TEXT"),
            ("messages_received", "INTEGER NOT NULL DEFAULT 0"),
            ("trial_notice_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("message_sent_last_date", "DATETIME"),
        ]:
            if column not in existing:
                self._conn.execute(f"ALTER TABLE subscribers ADD COLUMN {column} {definition}")

        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriber_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscriber_id INTEGER NOT NULL,
                filter_id INTEGER NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (subscriber_id, filter_id),
                FOREIGN KEY (subscriber_id) REFERENCES subscribers(id) ON DELETE CASCADE
            )
        """)

        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriber_filters_subscriber_id ON subscriber_filters(subscriber_id)
        """)
        self._conn.commit()

    def get_settings(self) -> dict:
        cur = self._conn.execute("SELECT stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days FROM bot_settings WHERE id = 1")
        row = cur.fetchone()
        return dict(row) if row else {
            "stars_price_monthly": 100,
            "stars_price_yearly": 1000,
            "trial_type": "messages",
            "trial_message_limit": 10,
            "trial_days": 2,
        }

    def get_subscriber_filters(self, chat_id: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute("""
                SELECT f.id, f.name, f.type, f.extra
                FROM filters f
                JOIN subscriber_filters sf ON f.id = sf.filter_id
                JOIN subscribers s ON sf.subscriber_id = s.id
                WHERE s.chat_id = ?
                ORDER BY f.created_at DESC
            """, (chat_id,))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def update_message_sent_date(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET message_sent_last_date = datetime('now') WHERE chat_id = ?",
                (chat_id,),
            )
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
