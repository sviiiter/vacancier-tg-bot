import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


BOT_TOKEN: str = _require("BOT_TOKEN")
CHAT_ID: str | None = os.getenv("CHAT_ID")  # Optional: only used for backwards-compat single-recipient mode
DB_DRIVER: str = os.getenv("DB_DRIVER", "sqlite")
DB_DSN: str = _require("DB_DSN")
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "10"))
POLL_INTERVAL_SEC: int = int(os.getenv("POLL_INTERVAL_SEC", "60"))
SEND_DELAY_SEC: float = float(os.getenv("SEND_DELAY_SEC", "0.5"))
STARS_PRICE_MONTHLY: int = int(os.getenv("STARS_PRICE_MONTHLY", "100"))
STARS_PRICE_YEARLY: int = int(os.getenv("STARS_PRICE_YEARLY", "1000"))
TRIAL_TYPE: str = os.getenv("TRIAL_TYPE", "messages")
TRIAL_MESSAGE_LIMIT: int = int(os.getenv("TRIAL_MESSAGE_LIMIT", "10"))
TRIAL_DAYS: int = int(os.getenv("TRIAL_DAYS", "2"))
