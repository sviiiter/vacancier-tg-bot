import json
import logging
import base64
import httpx
import redis
from datetime import datetime, timedelta
from bot.db.base import DatabaseDriver
from bot.sender import TelegramSender
from bot.trial import is_trial_active
from bot.filter_format import render_boolean_expression, render_preview_box
import bot.config as cfg
import html

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

    def _get_flow(self, chat_id: str) -> dict | None:
        """Get active flow state from Redis."""
        if not self._redis:
            return None
        try:
            flow_json = self._redis.get(f"flow:{chat_id}")
            return json.loads(flow_json) if flow_json else None
        except Exception as e:
            log.error("Error getting flow for %s: %s", chat_id, e)
            return None

    def _save_flow(self, chat_id: str, state: dict) -> None:
        """Save flow state to Redis with 10-minute TTL."""
        if not self._redis:
            return
        try:
            self._redis.setex(f"flow:{chat_id}", 600, json.dumps(state))
        except Exception as e:
            log.error("Error saving flow for %s: %s", chat_id, e)

    def _clear_flow(self, chat_id: str) -> None:
        """Clear flow state from Redis."""
        if not self._redis:
            return
        try:
            self._redis.delete(f"flow:{chat_id}")
        except Exception as e:
            log.error("Error clearing flow for %s: %s", chat_id, e)

    def handle_update(self, update: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Process a single update (commands, payments, etc.)."""
        if "message" in update:
            message = update["message"]
            if "document" in message:
                self._handle_document(message, driver, sender)
            else:
                self._handle_message(message, driver, sender)
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

        if not text.startswith("/"):
            flow = self._get_flow(chat_id)
            if flow and (flow.get("awaiting_custom_text") or flow.get("awaiting_name")):
                self._handle_flow_text_input(chat_id, text, flow, driver, sender)
                return

        if text in ["/start", "/subscribe"]:
            driver.add_subscriber(chat_id, username)
            self._send_reply(sender, chat_id, "✅ Subscribed! You'll now receive job postings.")
            self._send_and_pin_filter_menu(chat_id, sender)
            log.info("Subscriber added: chat_id=%s, username=%s", chat_id, username)

        elif text in ["/stop", "/unsubscribe"]:
            driver.remove_subscriber(chat_id)
            if self._redis:
                self._redis.delete(f"pending:{chat_id}")
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
<b>📚 Available Commands</b>

<b>Subscription:</b>
/start - Subscribe to job postings
/stop - Unsubscribe
/plan - View current plan and pricing
/upgrade - View subscription plans
/cancel - Cancel auto-renewal

<b>Filter Management:</b>
/filters - List your keyword filters
Filter menu appears on subscribe - Create/Remove filters via buttons

<b>Job Updates:</b>
/updates - Get latest matching job postings

<b>Info:</b>
/help - Show this message

<b>📋 About Filters</b>
Create filters to get only relevant job postings:
• Pick from shared filter library
• Build custom keyword filters (required, any, exclude)
• Upload CV for AI-based matching (coming soon)

Click the <b>➕ Create</b> button in your pinned menu to get started!
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

        if data.startswith("filter:"):
            self._handle_filter_callback(query_id, chat_id, data, driver, sender)
            return

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

    def _handle_filter_callback(self, query_id: str, chat_id: str, data: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Route filter: callbacks to appropriate handlers."""
        try:
            sender.answer_callback_query(query_id)
        except Exception as e:
            log.debug("Error answering callback query: %s", e)

        if data == "filter:create:start":
            self._handle_create_filter_start(chat_id, driver, sender)
        elif data == "filter:create:library":
            self._handle_create_filter_library(chat_id, driver, sender)
        elif data.startswith("filter:create:library:pick:"):
            filter_id = int(data.split(":")[-1])
            self._handle_create_filter_library_pick(chat_id, filter_id, driver, sender)
        elif data == "filter:create:build:json":
            self._handle_create_filter_build_json(chat_id, driver, sender)
        elif data == "filter:create:build:file":
            self._handle_create_filter_build_file(chat_id, driver, sender)
        elif data.startswith("filter:create:word:"):
            idx = int(data.split(":")[-1])
            self._handle_create_filter_word(chat_id, idx, driver, sender)
        elif data == "filter:create:custom":
            self._handle_create_filter_custom(chat_id, driver, sender)
        elif data.startswith("filter:create:step:"):
            step = data.split(":")[-1]
            self._handle_create_filter_step(chat_id, step, driver, sender)
        elif data == "filter:create:confirm":
            self._handle_create_filter_confirm(chat_id, driver, sender)
        elif data == "filter:create:cancel":
            self._handle_create_filter_cancel(chat_id, sender)
        elif data == "filter:remove:menu":
            self._handle_remove_filter_menu(chat_id, driver, sender)
        elif data.startswith("filter:remove:pick:"):
            filter_id = int(data.split(":")[-1])
            self._handle_remove_filter_pick(chat_id, filter_id, driver, sender)
        elif data == "filter:remove:all:ask":
            self._handle_remove_all_filters_ask(chat_id, sender)
        elif data == "filter:remove:all:yes":
            self._handle_remove_all_filters_yes(chat_id, driver, sender)
        elif data == "filter:remove:all:no":
            self._handle_remove_all_filters_no(chat_id, sender)
        elif data == "filter:remove:cancel":
            self._handle_remove_filter_cancel(chat_id, sender)
        else:
            log.warning("Unknown filter callback: %s", data)

    def _handle_create_filter_start(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Start the filter creation flow."""
        flow = {"step": "start", "type": None, "required": [], "any": [], "exclude": [], "known_words": []}
        self._save_flow(chat_id, flow)
        text = "📝 Create Filter\n\nChoose how to create your filter:"
        buttons = [
            ("📚 From Library", "filter:create:library"),
            ("🔨 Build Keyword Filter", "filter:create:build:json"),
            ("📄 Upload CV", "filter:create:build:file"),
            ("❌ Cancel", "filter:create:cancel"),
        ]
        sender.send_menu(chat_id, text, buttons)

    def _handle_create_filter_library(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Show available filters from the library."""
        try:
            filters = driver.list_filter_library()
            if not filters:
                sender.send_message("No filters available in the library yet.", chat_id)
                self._clear_flow(chat_id)
                return

            flow = {"step": "library", "type": None}
            self._save_flow(chat_id, flow)

            text = "📚 Available Filters:\n\nPick one to add to your collection:"
            buttons = []
            for f in filters[:10]:
                name = f.get("name", f"Filter #{f['id']}")
                buttons.append((f"✓ {name}", f"filter:create:library:pick:{f['id']}"))

            buttons.append(("❌ Cancel", "filter:create:cancel"))
            sender.send_menu(chat_id, text, buttons)
        except Exception as e:
            log.error("Error showing filter library for %s: %s", chat_id, e)
            sender.send_message("Error loading filter library.", chat_id)
            self._clear_flow(chat_id)

    def _handle_create_filter_library_pick(self, chat_id: str, filter_id: int, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Link subscriber to a library filter."""
        try:
            driver.link_subscriber_to_filter(chat_id, filter_id)
            sender.send_message("✅ Filter added to your collection!", chat_id)
            self._clear_flow(chat_id)
            log.info("Filter linked: chat_id=%s, filter_id=%s", chat_id, filter_id)
        except Exception as e:
            log.error("Error linking filter for %s: %s", chat_id, e)
            sender.send_message("Error adding filter. Please try again.", chat_id)
            self._clear_flow(chat_id)

    def _handle_create_filter_build_json(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Start building a keyword-based filter."""
        try:
            known_words = driver.get_known_keywords()
            flow = {
                "step": "required",
                "type": "json",
                "required": [],
                "any": [],
                "exclude": [],
                "known_words": known_words,
                "awaiting_custom_text": False,
            }
            self._save_flow(chat_id, flow)

            text = "📝 Build Keyword Filter - Step 1: Required Keywords\n\nPick words that <b>MUST</b> appear in the job title/description:"
            rows = []
            for i, word in enumerate(known_words[:12]):
                if i % 3 == 0:
                    rows.append([])
                rows[-1].append((word, f"filter:create:word:{i}"))

            rows.append([("➕ Add Custom", "filter:create:custom"), ("Next →", "filter:create:step:next")])
            sender.send_grid_menu(chat_id, text, rows)
        except Exception as e:
            log.error("Error building JSON filter for %s: %s", chat_id, e)
            sender.send_message("Error starting filter builder.", chat_id)
            self._clear_flow(chat_id)

    def _handle_create_filter_build_file(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Start CV file filter setup."""
        flow = {"step": "await_document", "type": "file"}
        self._save_flow(chat_id, flow)
        sender.send_message("📄 Upload your CV\n\nSend a PDF or document file to use for AI-based matching:", chat_id)

    def _handle_create_filter_word(self, chat_id: str, idx: int, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Toggle a keyword in the current filter step."""
        flow = self._get_flow(chat_id)
        if not flow:
            sender.send_message("No active filter creation. Use /add_filter to start.", chat_id)
            return

        known_words = flow.get("known_words", [])
        if idx >= len(known_words):
            log.warning("Word index out of range: chat_id=%s, idx=%d", chat_id, idx)
            return

        word = known_words[idx].lower()
        step = flow.get("step", "required")
        words_list = flow.get(step, [])

        if word in words_list:
            words_list.remove(word)
            action = "removed from"
        else:
            words_list.append(word)
            action = "added to"

        flow[step] = words_list
        self._save_flow(chat_id, flow)
        log.debug("Toggled word: chat_id=%s, word=%s, action=%s", chat_id, word, action)

    def _handle_create_filter_custom(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Ask for custom keyword input."""
        flow = self._get_flow(chat_id)
        if not flow:
            return

        flow["awaiting_custom_text"] = True
        self._save_flow(chat_id, flow)
        sender.send_message(f"Type a custom keyword for the <b>{flow.get('step', 'required')}</b> category (or /cancel):")

    def _handle_create_filter_step(self, chat_id: str, direction: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Move to next/previous step in keyword filter builder."""
        flow = self._get_flow(chat_id)
        if not flow:
            return

        step_order = ["required", "any", "exclude"]
        current_idx = step_order.index(flow.get("step", "required"))

        if direction == "next":
            next_idx = min(current_idx + 1, len(step_order) - 1)
            if next_idx == current_idx:
                flow["step"] = "name"
                flow["awaiting_name"] = True
                self._save_flow(chat_id, flow)
                sender.send_message("📝 Give your filter a name (or /cancel):", chat_id)
                return

            flow["step"] = step_order[next_idx]
        elif direction == "back":
            next_idx = max(current_idx - 1, 0)
            flow["step"] = step_order[next_idx]

        self._save_flow(chat_id, flow)
        self._handle_create_filter_build_json(chat_id, driver, sender)

    def _handle_create_filter_confirm(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Confirm and create the filter."""
        flow = self._get_flow(chat_id)
        if not flow:
            return

        try:
            rules = {
                "required": flow.get("required", []),
                "any": flow.get("any", []),
                "exclude": flow.get("exclude", []),
            }
            extra = json.dumps(rules)
            name = flow.get("name", "Unnamed Filter")
            file_id = flow.get("file_id")

            filter_id = driver.create_filter(name, flow.get("type", "json"), extra=extra if flow.get("type") == "json" else None, file_id=file_id if flow.get("type") == "file" else None)
            driver.link_subscriber_to_filter(chat_id, filter_id)

            self._clear_flow(chat_id)
            sender.send_message(f"✅ Filter '{name}' created and added to your collection!")
            log.info("Filter created: chat_id=%s, filter_id=%s, name=%s", chat_id, filter_id, name)
        except Exception as e:
            log.error("Error creating filter for %s: %s", chat_id, e)
            sender.send_message("Error creating filter. Please try again.", chat_id)
            self._clear_flow(chat_id)

    def _handle_create_filter_cancel(self, chat_id: str, sender: TelegramSender) -> None:
        """Cancel filter creation."""
        self._clear_flow(chat_id)
        sender.send_message("❌ Filter creation cancelled.", chat_id)

    def _handle_remove_filter_menu(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Show filters to remove."""
        try:
            filters = driver.get_subscriber_filters(chat_id)
            if not filters:
                sender.send_message("You have no filters to remove.", chat_id)
                return

            text = "🗑️ Remove Filter\n\nChoose a filter to remove (it will be unlinked from your account, not deleted):"
            buttons = []
            for f in filters:
                name = f.get("name", f"Filter #{f['id']}")
                buttons.append((f"❌ {name}", f"filter:remove:pick:{f['id']}"))
            buttons.append(("↩️ Back", "filter:create:start"))

            sender.send_menu(chat_id, text, buttons)
        except Exception as e:
            log.error("Error showing remove menu for %s: %s", chat_id, e)
            sender.send_message("Error loading filters.", chat_id)

    def _handle_remove_filter_pick(self, chat_id: str, filter_id: int, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Remove (unlink) a filter."""
        try:
            driver.unlink_subscriber_filter(chat_id, filter_id)
            sender.send_message("✅ Filter removed from your collection.", chat_id)
            log.info("Filter unlinked: chat_id=%s, filter_id=%s", chat_id, filter_id)
        except Exception as e:
            log.error("Error removing filter for %s: %s", chat_id, e)
            sender.send_message("Error removing filter.", chat_id)

    def _handle_remove_all_filters_ask(self, chat_id: str, sender: TelegramSender) -> None:
        """Confirm removing all filters."""
        text = "⚠️ Remove All Filters\n\nAre you sure you want to remove all filters?"
        buttons = [
            ("✅ Yes, remove all", "filter:remove:all:yes"),
            ("❌ No, cancel", "filter:remove:all:no"),
        ]
        sender.send_menu(chat_id, text, buttons)

    def _handle_remove_all_filters_yes(self, chat_id: str, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Remove all filters."""
        try:
            count = driver.unlink_all_subscriber_filters(chat_id)
            sender.send_message(f"✅ Removed {count} filter(s) from your collection.")
            log.info("All filters removed: chat_id=%s, count=%d", chat_id, count)
        except Exception as e:
            log.error("Error removing all filters for %s: %s", chat_id, e)
            sender.send_message("Error removing filters.", chat_id)

    def _handle_remove_all_filters_no(self, chat_id: str, sender: TelegramSender) -> None:
        """Cancel remove all filters."""
        sender.send_message("❌ Cancelled.", chat_id)

    def _handle_remove_filter_cancel(self, chat_id: str, sender: TelegramSender) -> None:
        """Cancel remove filter."""
        sender.send_message("❌ Cancelled.", chat_id)

    def _handle_flow_text_input(self, chat_id: str, text: str, flow: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle text input during an active wizard flow."""
        if flow.get("awaiting_custom_text"):
            word = text.lower().strip()
            step = flow.get("step", "required")
            words_list = flow.get(step, [])
            if word and word not in words_list:
                words_list.append(word)
                flow[step] = words_list
            flow["awaiting_custom_text"] = False
            self._save_flow(chat_id, flow)
            sender.send_message(f"✓ Added '{word}' to {step}. Continue building or proceed to the next step.")

        elif flow.get("awaiting_name"):
            name = text.strip()
            flow["name"] = name
            flow["awaiting_name"] = False
            self._save_flow(chat_id, flow)

            rules = {
                "required": flow.get("required", []),
                "any": flow.get("any", []),
                "exclude": flow.get("exclude", []),
            }
            expr = render_boolean_expression(rules)
            preview = driver.get_filter_preview(rules, limit=3)
            preview_box = render_preview_box(preview, rules)

            text_msg = f"<b>{name}</b>\n<code>{expr}</code>\n\n<pre>{html.escape(preview_box)}</pre>\n\n✅ Ready to save?"
            buttons = [
                ("💾 Save", "filter:create:confirm"),
                ("❌ Cancel", "filter:create:cancel"),
            ]
            sender.send_menu(chat_id, text_msg, buttons)

    def _handle_document(self, message: dict, driver: DatabaseDriver, sender: TelegramSender) -> None:
        """Handle document upload for CV-based filters."""
        chat_id = str(message.get("chat", {}).get("id"))
        flow = self._get_flow(chat_id)

        if not flow or flow.get("type") != "file" or flow.get("step") != "await_document":
            sender.send_message("No active file filter creation. Use the menu to create a filter.", chat_id)
            return

        try:
            doc = message.get("document", {})
            file_id = doc.get("file_id")
            filename = doc.get("file_name", "document")

            file_path = sender.get_file_path(file_id)
            content_bytes = sender.download_file(file_path)
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")

            stored_file_id = driver.insert_file(filename, content_b64)
            flow["file_id"] = stored_file_id
            flow["step"] = "name"
            flow["awaiting_name"] = True
            self._save_flow(chat_id, flow)

            sender.send_message(f"📄 File '{filename}' uploaded. Now give your filter a name:")
        except Exception as e:
            log.error("Error handling document for %s: %s", chat_id, e)
            sender.send_message("Error uploading file. Please try again.", chat_id)
            self._clear_flow(chat_id)

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
        """Handle /filters command - list user's filters with previews."""
        sub = driver.get_subscriber(chat_id)
        if not sub or not sub.get("active"):
            reply = "You must be subscribed to manage filters."
            self._send_reply(sender, chat_id, reply)
            return

        try:
            filters = driver.get_subscriber_filters(chat_id)
            if not filters:
                reply = "You have no filters configured yet.\nUse the filter menu to create one."
                self._send_reply(sender, chat_id, reply)
                return

            sender.send_message("📋 Your filters:", chat_id)
            for f in filters:
                filter_type = f.get("type", "unknown")
                name = f.get("name", "Unnamed")
                filter_id = f.get("id")

                if filter_type == "json":
                    extra_str = f.get("extra", "{}")
                    rules = json.loads(extra_str) if extra_str else {}
                    expr = render_boolean_expression(rules)
                    preview = driver.get_filter_preview(rules, limit=3)
                    preview_box = render_preview_box(preview, rules)
                    text = f"<b>{name}</b>\n<code>{expr}</code>\n\n<pre>{html.escape(preview_box)}</pre>"
                    sender.send_message(text, chat_id)
                else:
                    filename = driver.get_file_name(f.get("file_id")) if f.get("file_id") else "Unknown"
                    text = f"<b>{name}</b>\nCV file: {filename}\n(AI matching coming soon)"
                    sender.send_message(text, chat_id)

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

            # Send with filter creation button
            buttons = [
                ("➕ Create Filter", "filter:create:start"),
            ]
            sender.send_menu(chat_id, reply, buttons)

            # Clear pending messages and update last_sent_date
            self._redis.delete(key)
            driver.update_message_sent_date(chat_id)

            log.info("Sent %d updates to %s", len(messages), chat_id)
        except Exception as e:
            log.error("Error handling /updates for %s: %s", chat_id, e)
            reply = "Error loading updates. Please try again."
            self._send_reply(sender, chat_id, reply)

    def _send_and_pin_filter_menu(self, chat_id: str, sender: TelegramSender) -> None:
        """Send and pin the filter management menu on subscribe."""
        try:
            sender.unpin_all_chat_messages(chat_id)
        except Exception as e:
            log.debug("Warning unpinning messages for %s: %s", chat_id, e)

        try:
            text = "📋 Filter Management\n\n• <b>Create</b> - Add a new filter from shared library or build keyword rules\n• <b>Remove</b> - Unlink a filter\n• <b>Remove All</b> - Clear all filters\n\nUse the buttons below to manage your filters:"
            buttons = [
                ("➕ Create", "filter:create:start"),
                ("➖ Remove", "filter:remove:menu"),
                ("🗑️ Remove All", "filter:remove:all:ask"),
            ]
            msg_id = sender.send_menu(chat_id, text, buttons)
            sender.pin_chat_message(chat_id, msg_id)
            log.info("Pinned filter menu for %s", chat_id)
        except Exception as e:
            log.error("Error pinning filter menu for %s: %s", chat_id, e)

    def _send_reply(self, sender: TelegramSender, chat_id: str, text: str) -> None:
        """Send a reply message to the user."""
        try:
            sender.send_message(text, chat_id)
        except Exception as e:
            log.error("Error sending reply to %s: %s", chat_id, e)
