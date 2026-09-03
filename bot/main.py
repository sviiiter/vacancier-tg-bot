import logging
import time
import signal
import sys
import httpx

import bot.config as cfg
from bot.db import get_driver
from bot.sender import TelegramSender
from bot.updates import UpdateHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run() -> None:
    driver = get_driver(cfg.DB_DRIVER, cfg.DB_DSN)
    sender = TelegramSender(cfg.BOT_TOKEN, cfg.SEND_DELAY_SEC)
    client = httpx.Client(timeout=15)
    update_handler = UpdateHandler(cfg.BOT_TOKEN, client)

    def shutdown(sig, frame):
        log.info("Shutting down…")
        driver.close()
        sender.close()
        client.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info(
        "Started. driver=%s batch=%d interval=%ds",
        cfg.DB_DRIVER, cfg.BATCH_SIZE, cfg.POLL_INTERVAL_SEC,
    )

    update_offset = driver.get_last_update_id()

    while True:
        try:
            # Poll for incoming updates (subscribe/unsubscribe commands)
            updates = update_handler.get_updates(update_offset)
            for update in updates:
                try:
                    update_handler.handle_update(update, driver, sender)
                    update_offset = update["update_id"] + 1
                    driver.set_last_update_id(update_offset)
                except Exception as exc:
                    log.error("Error handling update id=%s: %s", update.get("update_id"), exc)

            # Fetch and broadcast pending messages to all subscribers
            rows = driver.get_pending(cfg.BATCH_SIZE)
            if rows:
                subscribers = driver.list_active_subscribers()
                if not subscribers:
                    log.debug("No active subscribers, skipping %d pending message(s).", len(rows))
                    driver.mark_sent([row["id"] for row in rows])
                else:
                    log.info("Broadcasting %d message(s) to %d subscriber(s)…", len(rows), len(subscribers))
                    sent_ids: list[int] = []
                    for row in rows:
                        failed_subscribers: list[str] = []
                        for chat_id in subscribers:
                            try:
                                sender.send_message(TelegramSender.format_message(row), chat_id)
                            except Exception as exc:
                                log.error("Failed to send message id=%s to chat_id=%s: %s", row["id"], chat_id, exc)
                                failed_subscribers.append(chat_id)
                        if len(failed_subscribers) < len(subscribers):
                            sent_ids.append(row["id"])
                    if sent_ids:
                        driver.mark_sent(sent_ids)
                        log.info("Marked %d message(s) as sent.", len(sent_ids))
            else:
                log.debug("No pending messages.")
        except Exception as exc:
            log.error("Loop error: %s", exc)

        time.sleep(cfg.POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()
