import json
import logging
import httpx
import redis
from datetime import datetime, timedelta
from bot.db.base import DatabaseDriver
from bot.sender import TelegramSender
from bot.trial import is_trial_active
import bot.config as cfg

log = logging.getLogger(__name__)


class UpdateHandler:
    _api_base = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, client: httpx.Client, redis_client: redis.Redis = None) -> None:
        self._token = token
        self._client = client
        self._redis = redis_client

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
            settings = driver.get_settings()
            reply = "💳 Choose your subscription plan:"
            buttons = [
                (f"Monthly ⭐{settings['stars_price_monthly']}", "buy:monthly"),
                (f"Yearly ⭐{settings['stars_price_yearly']}", "buy:yearly"),
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

        elif text == "/plan":
            self._handle_plan_command(chat_id, driver, sender)

        elif text == "/filters":
            self._handle_filters_command(chat_id, driver, sender)

        elif text == "/add_filter":
            reply = "Filter management coming soon!\nPlease contact support to add filters."
            self._send_reply(sender, chat_id, reply)

        elif text == "/updates":
            self._handle_updates_command(chat_id, driver, sender)

        elif text == "/help":
            reply = """
Available commands:
/start - Subscribe to job postings
/stop - Unsubscribe
/plan - View your current plan and pricing
/filters - List your keyword filters
/updates - Get latest matching job postings
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
        settings = driver.get_settings()

        if data == "buy:monthly":
            payload = f"{chat_id}:monthly"
            try:
                link = sender.create_invoice_link(
                    "Monthly Subscription",
                    "Unlimited access to job postings for 30 days",
                    payload,
                    settings["stars_price_monthly"],
                    subscription_period=2592000,
                )
                sender.send_invoice_link(
                    chat_id,
                    "💳 Subscribe to monthly plan:",
                    f"Pay ⭐{settings['stars_price_monthly']}/month",
                    link,
                )
                log.info("Sent monthly invoice link to %s", chat_id)
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
                    settings["stars_price_yearly"],
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

    def _handle_plan_command(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle /plan command."""
        sub = driver.get_subscriber(chat_id)
        settings = driver.get_settings()
        reply = self._format_plan_reply(sub, settings)
        self._send_reply(sender, chat_id, reply)

    @staticmethod
    def _format_plan_reply(sub: dict | None, settings: dict) -> str:
        """Format the /plan response."""
        if sub is None:
            reply = "📋 You're not yet subscribed!\n\n"
            reply += f"💰 Available plans:\n"
            reply += f"  Monthly: ⭐{settings['stars_price_monthly']} (auto-renews every 30 days)\n"
            reply += f"  Yearly: ⭐{settings['stars_price_yearly']} (covers 365 days)\n\n"
            reply += "Use /start to subscribe (free trial), then /upgrade to pick a paid plan."
            return reply

        reply = ""
        if sub["plan"] == "free":
            reply += "📋 You're on the <b>FREE</b> trial plan\n\n"
            if settings["trial_type"] == "messages":
                reply += f"📨 Trial progress: {sub.get('messages_received', 0)}/{settings['trial_message_limit']} messages\n"
            else:
                subscribed_at = sub.get("subscribed_at")
                if isinstance(subscribed_at, str):
                    subscribed_at = datetime.fromisoformat(subscribed_at.replace("Z", "+00:00"))
                elapsed_days = (datetime.now(subscribed_at.tzinfo if subscribed_at.tzinfo else None) - subscribed_at).days if subscribed_at.tzinfo else (datetime.now() - subscribed_at).days
                reply += f"📅 Trial progress: {elapsed_days}/{settings['trial_days']} days\n"
            reply += "\n💰 Available paid plans:\n"
            reply += f"  Monthly: ⭐{settings['stars_price_monthly']} (auto-renews every 30 days)\n"
            reply += f"  Yearly: ⭐{settings['stars_price_yearly']} (covers 365 days)\n\n"
            reply += "Use /upgrade to switch to a paid plan!"
        elif sub["plan"] == "monthly":
            reply += "📋 You're on the <b>MONTHLY</b> (auto-renewing) plan\n\n"
            expires_at = sub.get("expires_at")
            if expires_at:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                reply += f"✅ Active until: {expires_at.strftime('%Y-%m-%d')}\n\n"
            reply += "🔄 This plan auto-renews every 30 days.\n"
            reply += "Use /cancel to stop auto-renewal (you'll keep access until expiry)."
        elif sub["plan"] == "yearly":
            reply += "📋 You're on the <b>YEARLY</b> plan\n\n"
            expires_at = sub.get("expires_at")
            if expires_at:
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                reply += f"✅ Active until: {expires_at.strftime('%Y-%m-%d')}\n\n"
            reply += "Use /upgrade to renew when your plan expires."

        return reply

    def _handle_filters_command(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle /filters command - list user's filters."""
        sub = driver.get_subscriber(chat_id)
        if not sub or not sub.get("active"):
            reply = "You must be subscribed to manage filters."
            self._send_reply(sender, chat_id, reply)
            return

        try:
            filters = driver.get_subscriber_filters(chat_id)
            if not filters:
                reply = "You have no filters configured yet.\nUse /add_filter to create one."
                self._send_reply(sender, chat_id, reply)
                return

            reply = "📋 Your filters:\n\n"
            for f in filters:
                filter_type = f.get("type", "unknown")
                name = f.get("name", "Unnamed")
                if filter_type == "json":
                    keywords = f.get("extra", "")
                    reply += f"#{f['id']} {name}: {keywords}\n"
                else:
                    reply += f"#{f['id']} {name} (OpenAI)\n"

            self._send_reply(sender, chat_id, reply)
            log.info("Sent filters to %s", chat_id)
        except Exception as e:
            log.error("Error fetching filters for %s: %s", chat_id, e)
            reply = "Error loading filters. Please try again."
            self._send_reply(sender, chat_id, reply)

    def _handle_updates_command(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle /updates command - get pending messages from Redis."""
        sub = driver.get_subscriber(chat_id)
        if not sub or not sub.get("active"):
            reply = "You must be subscribed to receive updates."
            self._send_reply(sender, chat_id, reply)
            return

        if not self._redis:
            reply = "Updates service is temporarily unavailable."
            self._send_reply(sender, chat_id, reply)
            log.warning("Redis client not available for /updates command")
            return

        try:
            # Get pending message IDs from Redis
            key = f"pending:{chat_id}"
            message_ids = self._redis.smembers(key)

            if not message_ids:
                reply = "No new updates available at this time."
                self._send_reply(sender, chat_id, reply)
                return

            # Fetch messages from database
            message_ids_list = [int(m) for m in message_ids]
            messages = driver.get_messages_by_ids(message_ids_list)

            if not messages:
                reply = "No updates available."
                self._send_reply(sender, chat_id, reply)
                return

            reply = f"📋 Latest job updates ({len(messages)} new):\n\n"
            for msg in messages[:10]:  # Limit to 10 messages
                desc = msg.get("description", "")[:80].strip()
                link = msg.get("tg_message_link", "")
                reply += f"🔗 {link}\n{desc}...\n\n"

            self._send_reply(sender, chat_id, reply)

            # Clear pending messages and update last_sent_date
            self._redis.delete(key)
            driver.update_message_sent_date(chat_id)

            log.info("Sent %d updates to %s", len(messages), chat_id)
        except Exception as e:
            log.error("Error handling /updates for %s: %s", chat_id, e)
            reply = "Error loading updates. Please try again."
            self._send_reply(sender, chat_id, reply)

    def _send_reply(self, sender: TelegramSender, chat_id: str, text: str) -> None:
        """Send a reply message to the user."""
        try:
            sender.send_message(text, chat_id)
        except Exception as e:
            log.error("Error sending reply to %s: %s", chat_id, e)
