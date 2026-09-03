import json
import logging
import httpx
from datetime import datetime, timedelta
from bot.db.base import DatabaseDriver
from bot.sender import TelegramSender
import bot.config as cfg

log = logging.getLogger(__name__)


class UpdateHandler:
    _api_base = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, client: httpx.Client) -> None:
        self._token = token
        self._client = client

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        """Poll Telegram getUpdates endpoint."""
        url = self._api_base.format(token=self._token, method="getUpdates")
        params = {"offset": offset, "timeout": timeout}
        try:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", [])
        except Exception as e:
            log.error("Error fetching updates: %s", e)
            return []

    def handle_update(self, update: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Process a single update (commands, payments, etc.)."""
        if "message" in update:
            self._handle_message(update["message"], driver, sender)
        elif "callback_query" in update:
            self._handle_callback_query(update["callback_query"], driver, sender)
        elif "pre_checkout_query" in update:
            self._handle_pre_checkout_query(update["pre_checkout_query"], sender)
        elif "message" in update and "successful_payment" in update["message"]:
            self._handle_successful_payment(update["message"], driver, sender)

    def _handle_message(self, message: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle text commands."""
        chat_id = str(message.get("chat", {}).get("id"))
        username = message.get("from", {}).get("username")
        text = message.get("text", "").strip()

        if text in ["/start", "/subscribe"]:
            driver.add_subscriber(chat_id, username)
            reply = "✅ Subscribed! You'll now receive job postings."
            self._send_reply(sender, chat_id, reply)
            log.info("Subscriber added: chat_id=%s, username=%s", chat_id, username)

        elif text in ["/stop", "/unsubscribe"]:
            driver.remove_subscriber(chat_id)
            reply = "👋 Unsubscribed. You won't receive any more messages."
            self._send_reply(sender, chat_id, reply)
            log.info("Subscriber removed: chat_id=%s", chat_id)

        elif text == "/upgrade":
            reply = "💳 Choose your subscription plan:"
            buttons = [
                (f"Monthly ⭐{cfg.STARS_PRICE_MONTHLY}", "buy:monthly"),
                (f"Yearly ⭐{cfg.STARS_PRICE_YEARLY}", "buy:yearly"),
            ]
            try:
                sender.send_menu(chat_id, reply, buttons)
            except Exception as e:
                log.error("Error sending menu to %s: %s", chat_id, e)

        elif text == "/cancel":
            sub = driver.get_subscriber(chat_id)
            if sub and sub.get("star_charge_id"):
                try:
                    sender.cancel_star_subscription(chat_id, sub["star_charge_id"])
                    reply = "✅ Auto-renewal cancelled. Access continues until your subscription expires."
                    self._send_reply(sender, chat_id, reply)
                    log.info("Subscription cancelled: chat_id=%s", chat_id)
                except Exception as e:
                    log.error("Error cancelling subscription for %s: %s", chat_id, e)
                    reply = "❌ Failed to cancel subscription. Please try again."
                    self._send_reply(sender, chat_id, reply)
            else:
                reply = "No active subscription to cancel."
                self._send_reply(sender, chat_id, reply)

        elif text == "/help":
            reply = """
Available commands:
/start - Subscribe to job postings
/stop - Unsubscribe
/upgrade - View subscription plans
/cancel - Cancel auto-renewal
/help - Show this message
"""
            self._send_reply(sender, chat_id, reply)

        elif "successful_payment" in message:
            self._handle_successful_payment(message, driver, sender)

    def _handle_callback_query(self, callback_query: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle inline button presses."""
        query_id = callback_query.get("id")
        chat_id = str(callback_query.get("from", {}).get("id"))
        data = callback_query.get("data", "")

        if data == "buy:monthly":
            payload = f"{chat_id}:monthly"
            try:
                sender.send_invoice(
                    chat_id,
                    "Monthly Subscription",
                    "Unlimited access to job postings for 30 days",
                    payload,
                    cfg.STARS_PRICE_MONTHLY,
                    subscription_period=2592000,
                )
                log.info("Sent monthly invoice to %s", chat_id)
            except Exception as e:
                log.error("Error sending monthly invoice to %s: %s", chat_id, e)

        elif data == "buy:yearly":
            payload = f"{chat_id}:yearly"
            try:
                sender.send_invoice(
                    chat_id,
                    "Yearly Subscription",
                    "Unlimited access to job postings for 365 days",
                    payload,
                    cfg.STARS_PRICE_YEARLY,
                    subscription_period=None,
                )
                log.info("Sent yearly invoice to %s", chat_id)
            except Exception as e:
                log.error("Error sending yearly invoice to %s: %s", chat_id, e)

    def _handle_pre_checkout_query(self, pre_checkout_query: dict, sender: TelegramSender) -> None:
        """Always approve pre-checkout (no validation needed)."""
        query_id = pre_checkout_query.get("id")
        try:
            sender.answer_pre_checkout_query(query_id, ok=True)
            log.debug("Pre-checkout approved: query_id=%s", query_id)
        except Exception as e:
            log.error("Error approving pre-checkout %s: %s", query_id, e)

    def _handle_successful_payment(self, message: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Process a successful payment."""
        payment = message.get("successful_payment", {})
        if not payment:
            return

        chat_id = str(message.get("chat", {}).get("id"))
        charge_id = payment.get("telegram_payment_charge_id")
        invoice_payload = payment.get("invoice_payload", "")

        if not charge_id or not invoice_payload:
            log.warning("Invalid payment: missing charge_id or payload")
            return

        try:
            plan = invoice_payload.split(":")[-1] if ":" in invoice_payload else "monthly"
        except Exception:
            plan = "monthly"

        amount = payment.get("total_amount", 0)
        is_recurring = 1 if plan == "monthly" else 0

        if not driver.record_payment(chat_id, plan, amount, charge_id, is_recurring):
            log.info("Duplicate payment recorded (idempotency): chat_id=%s, charge_id=%s", chat_id, charge_id)
            return

        if plan == "monthly":
            expires_at = (datetime.now() + timedelta(days=30)).isoformat()
        else:
            expires_at = (datetime.now() + timedelta(days=365)).isoformat()

        driver.activate_paid_plan(chat_id, plan, expires_at, charge_id)

        expiry_date = expires_at.split("T")[0]
        reply = f"🎉 Payment successful! Your {plan} subscription is active until {expiry_date}."
        self._send_reply(sender, chat_id, reply)
        log.info("Payment processed: chat_id=%s, plan=%s, charge_id=%s", chat_id, plan, charge_id)

    def _send_reply(self, sender: TelegramSender, chat_id: str, text: str) -> None:
        """Send a reply message to the user."""
        try:
            sender.send_message(text, chat_id)
        except Exception as e:
            log.error("Error sending reply to %s: %s", chat_id, e)
