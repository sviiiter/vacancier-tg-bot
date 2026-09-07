import logging
import time
import signal
import sys
import httpx
import redis

import bot.config as cfg
from bot.db import get_driver
from bot.sender import TelegramSender
from bot.updates import UpdateHandler
from bot.trial import is_trial_active

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def run() -> None:
    driver = get_driver(cfg.DB_DRIVER, cfg.DB_DSN)
    sender = TelegramSender(cfg.BOT_TOKEN, cfg.SEND_DELAY_SEC)
    client = httpx.Client(timeout=40)
    redis_client = redis.from_url(cfg.REDIS_URL)
    update_handler = UpdateHandler(cfg.BOT_TOKEN, client, redis_client)

    def shutdown(sig, frame):
        log.info("Shutting down…")
        driver.close()
        sender.close()
        client.close()
        redis_client.close()
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
            # Poll for incoming updates (commands, payments, etc.)
            updates = update_handler.get_updates(update_offset)

            # Pass 1: answer pre_checkout_query immediately (Telegram allows ~10s)
            # This must happen before any slow work (broadcast loop, expiry sweep)
            for update in updates:
                if "pre_checkout_query" in update:
                    try:
                        update_handler.handle_update(update, driver, sender)
                    except Exception as exc:
                        log.error("Error handling pre_checkout_query id=%s: %s", update.get("update_id"), exc)
                        driver.rollback()

            # Pass 2: handle all other updates and advance offset for all in order
            for update in updates:
                if "pre_checkout_query" in update:
                    update_offset = update["update_id"] + 1
                    driver.set_last_update_id(update_offset)
                    continue
                try:
                    update_handler.handle_update(update, driver, sender)
                    update_offset = update["update_id"] + 1
                    driver.set_last_update_id(update_offset)
                except Exception as exc:
                    log.error("Error handling update id=%s: %s", update.get("update_id"), exc)
                    driver.rollback()

            # Downgrade expired subscribers
            expired = driver.downgrade_expired_subscribers()
            for chat_id in expired:
                try:
                    sender.send_message("Your subscription has expired. Use /upgrade to renew.", chat_id)
                    log.info("Notified expired subscriber: chat_id=%s", chat_id)
                except Exception as exc:
                    log.error("Failed to notify expired subscriber %s: %s", chat_id, exc)

            # Fetch and deliver staged messages from Redis (per-subscriber)
            chat_ids = redis_client.smembers("pending:index")
            if chat_ids:
                settings = driver.get_settings()
                for chat_id in chat_ids:
                    chat_id_str = chat_id.decode() if isinstance(chat_id, bytes) else chat_id
                    pending_ids = redis_client.smembers(f"pending:{chat_id_str}")

                    if not pending_ids:
                        redis_client.srem("pending:index", chat_id_str)
                        continue

                    sub = driver.get_subscriber(chat_id_str)
                    if not sub or not sub["active"]:
                        log.debug("Subscriber %s not found or inactive, skipping", chat_id_str)
                        continue

                    if not is_trial_active(sub, settings["trial_type"], settings["trial_message_limit"], settings["trial_days"]):
                        if not sub["trial_notice_sent"]:
                            try:
                                sender.send_message(
                                    "Your free trial has ended. Use /upgrade to keep receiving job postings.",
                                    chat_id_str,
                                )
                                driver.mark_trial_notice_sent(chat_id_str)
                                log.info("Sent trial-ended notice to chat_id=%s", chat_id_str)
                            except Exception as exc:
                                log.error("Failed to send trial-ended notice to %s: %s", chat_id_str, exc)
                        continue

                    message_ids = [int(mid.decode() if isinstance(mid, bytes) else mid) for mid in pending_ids]
                    messages = driver.get_messages_by_ids(message_ids)

                    last_created_date = None
                    free_count = 0

                    for msg in messages:
                        try:
                            sender.send_message(TelegramSender.format_message(msg), chat_id_str)
                            redis_client.srem(f"pending:{chat_id_str}", msg["id"])
                            last_created_date = msg["created_date"]
                            if sub["plan"] == "free":
                                free_count += 1
                        except Exception as exc:
                            log.error("Failed to send message id=%s to chat_id=%s: %s", msg["id"], chat_id_str, exc)
                            break

                    if last_created_date:
                        driver.update_message_sent_last_date(chat_id_str, last_created_date)
                        if free_count > 0:
                            driver.increment_messages_received([chat_id_str] * free_count)
                        log.info("Delivered to chat_id=%s, updated message_sent_last_date", chat_id_str)

                    if redis_client.scard(f"pending:{chat_id_str}") == 0:
                        redis_client.srem("pending:index", chat_id_str)
            else:
                log.debug("No pending messages.")
        except Exception as exc:
            log.error("Loop error: %s", exc)
            driver.rollback()

        time.sleep(cfg.POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()
