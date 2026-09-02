import json
import logging
import httpx
from bot.db.base import DatabaseDriver
from bot.sender import TelegramSender

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
        """Process a single update (subscribe/unsubscribe commands)."""
        if "message" not in update:
            return

        message = update["message"]
        chat_id = str(message.get("chat_id"))
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

        elif text == "/help":
            reply = """
Available commands:
/start - Subscribe to job postings
/stop - Unsubscribe
/help - Show this message
"""
            self._send_reply(sender, chat_id, reply)

    def _send_reply(self, sender: TelegramSender, chat_id: str, text: str) -> None:
        """Send a reply message to the user."""
        try:
            sender.send_message(text, chat_id)
        except Exception as e:
            log.error("Error sending reply to %s: %s", chat_id, e)
