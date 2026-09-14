import os
import json
from collections import Counter
import psycopg2
import psycopg2.extras
from bot.db.base import DatabaseDriver
from bot.filter_rules import extract_known_keywords


class PostgresDriver(DatabaseDriver):
    def __init__(self, dsn: str) -> None:
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._init_schema()

    def get_messages_by_ids(self, ids: list[int]) -> list[dict]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM messages WHERE id = ANY(%s) ORDER BY created_date ASC",
                (ids,),
            )
            return [dict(row) for row in cur.fetchall()]

    def update_message_sent_last_date(self, chat_id: str, ts) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET message_sent_last_date = %s WHERE chat_id = %s AND (message_sent_last_date IS NULL OR message_sent_last_date < %s)",
                (ts, chat_id, ts),
            )
        self._conn.commit()

    def add_subscriber(self, chat_id: str, username: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO subscribers (chat_id, username, active, messages_received, message_sent_last_date)
                   VALUES (%s, %s, 1, 0, NULL)
                   ON CONFLICT (chat_id) DO UPDATE SET active = 1, username = EXCLUDED.username""",
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

    def record_payment(self, chat_id: str, plan: str, amount: int, charge_id: str, is_recurring: int) -> bool:
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO payments (chat_id, plan, amount, telegram_payment_charge_id, is_recurring)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (chat_id, plan, amount, charge_id, is_recurring),
                )
            self._conn.commit()
            return True
        except psycopg2.IntegrityError:
            self._conn.rollback()
            return False

    def activate_paid_plan(self, chat_id: str, plan: str, expires_at: str, charge_id: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE subscribers SET plan = %s, expires_at = %s, star_charge_id = %s, active = 1
                   WHERE chat_id = %s""",
                (plan, expires_at, charge_id, chat_id),
            )
        self._conn.commit()

    def get_subscriber(self, chat_id: str) -> dict | None:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM subscribers WHERE chat_id = %s", (chat_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def downgrade_expired_subscribers(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                """UPDATE subscribers SET plan = 'free', expires_at = NULL, star_charge_id = NULL
                   WHERE plan != 'free' AND expires_at < now() RETURNING chat_id"""
            )
            expired = [row[0] for row in cur.fetchall()]
        self._conn.commit()
        return expired

    def increment_messages_received(self, chat_ids: list[str]) -> None:
        if not chat_ids:
            return
        with self._conn.cursor() as cur:
            for chat_id, count in Counter(chat_ids).items():
                cur.execute(
                    "UPDATE subscribers SET messages_received = messages_received + %s WHERE chat_id = %s",
                    (count, chat_id),
                )
        self._conn.commit()

    def mark_trial_notice_sent(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET trial_notice_sent = 1 WHERE chat_id = %s",
                (chat_id,),
            )
        self._conn.commit()

    def create_filter(self, name: str, filter_type: str, extra: str | None = None, file_id: int | None = None) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO filters (name, type, extra, file_id) VALUES (%s, %s, %s, %s) RETURNING id",
                (name, filter_type, extra, file_id),
            )
            new_id = cur.fetchone()[0]
        self._conn.commit()
        return new_id

    def link_subscriber_to_filter(self, chat_id: str, filter_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """INSERT INTO subscriber_filters (subscriber_id, filter_id)
                   SELECT id, %s FROM subscribers WHERE chat_id = %s
                   ON CONFLICT (subscriber_id, filter_id) DO NOTHING""",
                (filter_id, chat_id),
            )
        self._conn.commit()

    def unlink_subscriber_filter(self, chat_id: str, filter_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """DELETE FROM subscriber_filters
                   WHERE filter_id = %s
                     AND subscriber_id = (SELECT id FROM subscribers WHERE chat_id = %s)""",
                (filter_id, chat_id),
            )
        self._conn.commit()

    def unlink_all_subscriber_filters(self, chat_id: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """DELETE FROM subscriber_filters
                   WHERE subscriber_id = (SELECT id FROM subscribers WHERE chat_id = %s)""",
                (chat_id,),
            )
            n = cur.rowcount
        self._conn.commit()
        return n

    def list_filter_library(self) -> list[dict]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id, name, type, extra, file_id FROM filters ORDER BY created_at DESC")
            return [dict(row) for row in cur.fetchall()]

    def get_known_keywords(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT extra FROM filters WHERE extra IS NOT NULL")
            extras = [row[0] for row in cur.fetchall()]
        return extract_known_keywords(extras)

    def get_file_name(self, file_id: int) -> str | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT filename FROM file WHERE id = %s", (file_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def insert_file(self, filename: str, content: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute("INSERT INTO file (filename, content) VALUES (%s, %s) RETURNING id", (filename, content))
            new_id = cur.fetchone()[0]
        self._conn.commit()
        return new_id

    def get_filter_preview(self, rules: dict, limit: int = 3) -> dict:
        # Note: preview uses message_filters table which only reflects matches already processed by the matcher
        # New filters won't show previews until the next matcher run
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # This is a placeholder - get_filter_preview is not actually used since filters are new
            # and message_filters won't have entries yet. We just return empty preview.
            return {"count": 0, "samples": []}

    def _init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL UNIQUE,
                    username TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    plan TEXT NOT NULL DEFAULT 'free',
                    subscribed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at TIMESTAMPTZ,
                    star_charge_id TEXT,
                    messages_received INTEGER NOT NULL DEFAULT 0,
                    trial_notice_sent INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'stars',
                    telegram_payment_charge_id TEXT UNIQUE,
                    is_recurring INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
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
            cur.execute(
                """INSERT INTO bot_settings (id, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO NOTHING""",
                (1, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days),
            )
            for column, definition in [
                ("expires_at", "TIMESTAMPTZ"),
                ("star_charge_id", "TEXT"),
                ("messages_received", "INTEGER NOT NULL DEFAULT 0"),
                ("trial_notice_sent", "INTEGER NOT NULL DEFAULT 0"),
                ("message_sent_last_date", "TIMESTAMPTZ"),
            ]:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = 'subscribers' AND column_name = %s",
                    (column,),
                )
                if cur.fetchone() is None:
                    cur.execute(f'ALTER TABLE subscribers ADD COLUMN "{column}" {definition}')

            cur.execute("""
                CREATE TABLE IF NOT EXISTS file (
                    id       SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content  TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS filters (
                    id         SERIAL PRIMARY KEY,
                    name       TEXT,
                    type       TEXT NOT NULL DEFAULT 'json' CHECK (type IN ('file','json')),
                    extra      TEXT,
                    file_id    INTEGER REFERENCES file(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)

            for column, definition in [
                ("name", "TEXT"),
                ("created_at", "TIMESTAMPTZ NOT NULL DEFAULT now()"),
            ]:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = 'filters' AND column_name = %s",
                    (column,),
                )
                if cur.fetchone() is None:
                    cur.execute(f'ALTER TABLE filters ADD COLUMN "{column}" {definition}')

            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              SERIAL PRIMARY KEY,
                    description     TEXT NOT NULL,
                    tg_channel_link TEXT NOT NULL,
                    tg_message_link TEXT NOT NULL UNIQUE,
                    created_date    TIMESTAMPTZ NOT NULL,
                    source          TEXT NOT NULL DEFAULT 'telegram',
                    queue_sent      INTEGER NOT NULL DEFAULT 0,
                    read            INTEGER NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS message_filters (
                    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    filter_id  INTEGER NOT NULL REFERENCES filters(id) ON DELETE CASCADE,
                    matched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (message_id, filter_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriber_filters (
                    id            SERIAL PRIMARY KEY,
                    subscriber_id INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
                    filter_id     INTEGER NOT NULL,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (subscriber_id, filter_id)
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriber_filters_subscriber_id ON subscriber_filters(subscriber_id)
            """)
        self._conn.commit()

    def get_settings(self) -> dict:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days FROM bot_settings WHERE id = 1")
            row = cur.fetchone()
        return dict(row) if row else {
            "stars_price_monthly": 100,
            "stars_price_yearly": 1000,
            "trial_type": "messages",
            "trial_message_limit": 10,
            "trial_days": 2,
        }

    def get_subscriber_filters(self, chat_id: str) -> list[dict]:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT f.id, f.name, f.type, f.extra, f.file_id
                FROM filters f
                JOIN subscriber_filters sf ON f.id = sf.filter_id
                JOIN subscribers s ON sf.subscriber_id = s.id
                WHERE s.chat_id = %s
                ORDER BY f.created_at DESC
            """, (chat_id,))
            return [dict(row) for row in cur.fetchall()]

    def update_message_sent_date(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET message_sent_last_date = now() WHERE chat_id = %s",
                (chat_id,),
            )
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
