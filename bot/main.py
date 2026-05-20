import logging
import time
import signal
import sys

import bot.config as cfg
from bot.db import get_driver
from bot.sender import TelegramSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run() -> None:
    driver = get_driver(cfg.DB_DRIVER, cfg.DB_DSN)
    sender = TelegramSender(cfg.BOT_TOKEN, cfg.CHAT_ID, cfg.SEND_DELAY_SEC)

    def shutdown(sig, frame):
        log.info("Shutting down…")
        driver.close()
        sender.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info(
        "Started. driver=%s batch=%d interval=%ds",
        cfg.DB_DRIVER, cfg.BATCH_SIZE, cfg.POLL_INTERVAL_SEC,
    )

    while True:
        try:
            rows = driver.get_pending(cfg.BATCH_SIZE)
            if rows:
                log.info("Sending %d message(s)…", len(rows))
                sent_ids: list[int] = []
                for row in rows:
                    try:
                        sender.send_message(TelegramSender.format_message(row))
                        sent_ids.append(row["id"])
                    except Exception as exc:
                        log.error("Failed to send message id=%s: %s", row["id"], exc)
                if sent_ids:
                    driver.mark_sent(sent_ids)
                    log.info("Marked %d message(s) as sent.", len(sent_ids))
            else:
                log.debug("No pending messages.")
        except Exception as exc:
            log.error("Poll error: %s", exc)

        time.sleep(cfg.POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()
