import os
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

    def get_messages_by_ids(self, ids: list[int]) -> list[dict]:
        placeholders = ",".join(["%s"] * len(ids))
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY created_date ASC",
                ids,
            )
            return cur.fetchall()

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
        except pymysql.IntegrityError:
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
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM subscribers WHERE chat_id = %s", (chat_id,))
            row = cur.fetchone()
        return row

    def downgrade_expired_subscribers(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT chat_id FROM subscribers
                   WHERE plan != 'free' AND expires_at < NOW()"""
            )
            expired = [row["chat_id"] for row in cur.fetchall()]
            if expired:
                placeholders = ",".join(["%s"] * len(expired))
                cur.execute(
                    f"""UPDATE subscribers SET plan = 'free', expires_at = NULL, star_charge_id = NULL
                       WHERE chat_id IN ({placeholders})""",
                    expired,
                )
        self._conn.commit()
        return expired

    def increment_messages_received(self, chat_ids: list[str]) -> None:
        if not chat_ids:
            return
        placeholders = ",".join(["%s"] * len(chat_ids))
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE subscribers SET messages_received = messages_received + 1 WHERE chat_id IN ({placeholders})",
                chat_ids,
            )
        self._conn.commit()

    def mark_trial_notice_sent(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET trial_notice_sent = 1 WHERE chat_id = %s",
                (chat_id,),
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
                    subscribed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    star_charge_id VARCHAR(255),
                    messages_received INT NOT NULL DEFAULT 0,
                    trial_notice_sent INT NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    `key` VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    chat_id VARCHAR(255) NOT NULL,
                    plan VARCHAR(50) NOT NULL,
                    amount INT NOT NULL,
                    provider VARCHAR(50) NOT NULL DEFAULT 'stars',
                    telegram_payment_charge_id VARCHAR(255) UNIQUE,
                    is_recurring INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id INT PRIMARY KEY,
                    stars_price_monthly INT NOT NULL DEFAULT 100,
                    stars_price_yearly INT NOT NULL DEFAULT 1000,
                    trial_type VARCHAR(50) NOT NULL DEFAULT 'messages',
                    trial_message_limit INT NOT NULL DEFAULT 10,
                    trial_days INT NOT NULL DEFAULT 2
                )
            """)
            stars_price_monthly = int(os.getenv("STARS_PRICE_MONTHLY", "100"))
            stars_price_yearly = int(os.getenv("STARS_PRICE_YEARLY", "1000"))
            trial_type = os.getenv("TRIAL_TYPE", "messages")
            trial_message_limit = int(os.getenv("TRIAL_MESSAGE_LIMIT", "10"))
            trial_days = int(os.getenv("TRIAL_DAYS", "2"))
            cur.execute(
                """INSERT IGNORE INTO bot_settings (id, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (1, stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days),
            )
            for column, definition in [
                ("expires_at", "DATETIME"),
                ("star_charge_id", "VARCHAR(255)"),
                ("messages_received", "INT NOT NULL DEFAULT 0"),
                ("trial_notice_sent", "INT NOT NULL DEFAULT 0"),
                ("message_sent_last_date", "DATETIME"),
            ]:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'subscribers' AND column_name = %s",
                    (column,),
                )
                if cur.fetchone() is None:
                    cur.execute(f"ALTER TABLE subscribers ADD COLUMN `{column}` {definition}")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriber_filters (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    subscriber_id INT NOT NULL,
                    filter_id INT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (subscriber_id, filter_id),
                    FOREIGN KEY (subscriber_id) REFERENCES subscribers(id) ON DELETE CASCADE
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriber_filters_subscriber_id ON subscriber_filters(subscriber_id)
            """)
        self._conn.commit()

    def get_settings(self) -> dict:
        with self._conn.cursor() as cur:
            cur.execute("SELECT stars_price_monthly, stars_price_yearly, trial_type, trial_message_limit, trial_days FROM bot_settings WHERE id = 1")
            row = cur.fetchone()
        return row if row else {
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
                WHERE s.chat_id = %s
                ORDER BY f.created_at DESC
            """, (chat_id,))
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def update_message_sent_date(self, chat_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE subscribers SET message_sent_last_date = NOW() WHERE chat_id = %s",
                (chat_id,),
            )
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()
