import logging
import time
import signal
import sys
import httpx

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
            # Poll for incoming updates (commands, payments, etc.)
            updates = update_handler.get_updates(update_offset)
            for update in updates:
                try:
                    update_handler.handle_update(update, driver, sender)
                    update_offset = update["update_id"] + 1
                    driver.set_last_update_id(update_offset)
                except Exception as exc:
                    log.error("Error handling update id=%s: %s", update.get("update_id"), exc)

            # Downgrade expired subscribers
            expired = driver.downgrade_expired_subscribers()
            for chat_id in expired:
                try:
                    sender.send_message("Your subscription has expired. Use /upgrade to renew.", chat_id)
                    log.info("Notified expired subscriber: chat_id=%s", chat_id)
                except Exception as exc:
                    log.error("Failed to notify expired subscriber %s: %s", chat_id, exc)

            # Fetch and broadcast pending messages to eligible subscribers
            rows = driver.get_pending(cfg.BATCH_SIZE)
            if rows:
                all_subs = driver.list_broadcastable_subscribers()
                if not all_subs:
                    log.debug("No active subscribers, skipping %d pending message(s).", len(rows))
                    driver.mark_sent([row["id"] for row in rows])
                else:
                    log.info("Broadcasting %d message(s) to %d active subscriber(s)…", len(rows), len(all_subs))
                    sent_ids: list[int] = []
                    received_by_free: list[str] = []

                    for row in rows:
                        failed_subscribers: list[str] = []
                        trial_locked_out: list[str] = []

                        for sub in all_subs:
                            chat_id = sub["chat_id"]
                            if not is_trial_active(sub, cfg.TRIAL_TYPE, cfg.TRIAL_MESSAGE_LIMIT, cfg.TRIAL_DAYS):
                                trial_locked_out.append(chat_id)
                                continue

                            try:
                                sender.send_message(TelegramSender.format_message(row), chat_id)
                                if sub["plan"] == "free":
                                    received_by_free.append(chat_id)
                            except Exception as exc:
                                log.error("Failed to send message id=%s to chat_id=%s: %s", row["id"], chat_id, exc)
                                failed_subscribers.append(chat_id)

                        if len(failed_subscribers) < len(all_subs):
                            sent_ids.append(row["id"])

                        if received_by_free:
                            driver.increment_messages_received(received_by_free)

                    # Send trial-ended notices to locked-out free subscribers (once per user)
                    for sub in all_subs:
                        if (
                            sub["plan"] == "free"
                            and not is_trial_active(sub, cfg.TRIAL_TYPE, cfg.TRIAL_MESSAGE_LIMIT, cfg.TRIAL_DAYS)
                            and not sub["trial_notice_sent"]
                        ):
                            try:
                                sender.send_message(
                                    "Your free trial has ended. Use /upgrade to keep receiving job postings.",
                                    sub["chat_id"],
                                )
                                driver.mark_trial_notice_sent(sub["chat_id"])
                                log.info("Sent trial-ended notice to chat_id=%s", sub["chat_id"])
                            except Exception as exc:
                                log.error("Failed to send trial-ended notice to %s: %s", sub["chat_id"], exc)

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
