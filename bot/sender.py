import json
import time
import logging
import httpx

log = logging.getLogger(__name__)


class TelegramSender:
    _api_base = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, send_delay: float = 0.5) -> None:
        self._token = token
        self._send_delay = send_delay
        self._client = httpx.Client(timeout=15)

    def send_message(self, text: str, chat_id: str) -> None:
        url = self._api_base.format(token=self._token, method="sendMessage")
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        log.debug("Sending message - chat_id=%s, text_len=%d", chat_id, len(text))
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        time.sleep(self._send_delay)

    def create_invoice_link(self, title: str, description: str, payload: str, amount_stars: int, subscription_period: int | None = None) -> str:
        url = self._api_base.format(token=self._token, method="createInvoiceLink")
        invoice_payload = {
            "title": title,
            "description": description,
            "payload": payload,
            "currency": "XTR",
            "prices": [{"label": title, "amount": amount_stars}],
        }
        if subscription_period:
            invoice_payload["subscription_period"] = subscription_period
        log.debug("Creating invoice link - title=%s, amount=%d", title, amount_stars)
        resp = self._client.post(url, json=invoice_payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["result"]

    def send_invoice(self, chat_id: str, title: str, description: str, payload: str, amount_stars: int) -> None:
        url = self._api_base.format(token=self._token, method="sendInvoice")
        invoice_payload = {
            "chat_id": chat_id,
            "title": title,
            "description": description,
            "payload": payload,
            "currency": "XTR",
            "prices": [{"label": title, "amount": amount_stars}],
        }
        log.debug("Sending invoice - chat_id=%s, plan=%s, amount=%d", chat_id, title, amount_stars)
        resp = self._client.post(url, json=invoice_payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def send_invoice_link(self, chat_id: str, text: str, button_text: str, url: str) -> None:
        api_url = self._api_base.format(token=self._token, method="sendMessage")
        keyboard = {"inline_keyboard": [[{"text": button_text, "url": url}]]}
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard}
        log.debug("Sending invoice link - chat_id=%s, button=%s", chat_id, button_text)
        resp = self._client.post(api_url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        time.sleep(self._send_delay)

    def answer_pre_checkout_query(self, pre_checkout_query_id: str, ok: bool = True, error_message: str | None = None) -> None:
        url = self._api_base.format(token=self._token, method="answerPreCheckoutQuery")
        payload = {"pre_checkout_query_id": pre_checkout_query_id, "ok": ok}
        if error_message:
            payload["error_message"] = error_message
        log.debug("Answering pre-checkout query - query_id=%s, ok=%s", pre_checkout_query_id, ok)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def send_menu(self, chat_id: str, text: str, buttons: list[tuple[str, str]]) -> int:
        url = self._api_base.format(token=self._token, method="sendMessage")
        keyboard = {"inline_keyboard": [[{"text": btn_text, "callback_data": btn_data}] for btn_text, btn_data in buttons]}
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard}
        log.debug("Sending menu - chat_id=%s, options=%d", chat_id, len(buttons))
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]

    def cancel_star_subscription(self, chat_id: str, charge_id: str) -> None:
        url = self._api_base.format(token=self._token, method="editUserStarSubscription")
        payload = {"user_id": chat_id, "telegram_payment_charge_id": charge_id, "is_canceled": True}
        log.debug("Cancelling subscription - chat_id=%s, charge_id=%s", chat_id, charge_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def send_grid_menu(self, chat_id: str, text: str, rows: list[list[tuple[str, str]]]) -> int:
        url = self._api_base.format(token=self._token, method="sendMessage")
        keyboard = {"inline_keyboard": [[{"text": btn_text, "callback_data": btn_data} for btn_text, btn_data in row] for row in rows]}
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard}
        log.debug("Sending grid menu - chat_id=%s", chat_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]

    def edit_message_text(self, chat_id: str, message_id: int, text: str, rows: list[list[tuple[str, str]]] | None = None) -> None:
        url = self._api_base.format(token=self._token, method="editMessageText")
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
        if rows is not None:
            keyboard = {"inline_keyboard": [[{"text": btn_text, "callback_data": btn_data} for btn_text, btn_data in row] for row in rows]}
            payload["reply_markup"] = keyboard
        log.debug("Editing message - chat_id=%s, message_id=%s", chat_id, message_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def answer_callback_query(self, callback_query_id: str, text: str | None = None, show_alert: bool = False) -> None:
        url = self._api_base.format(token=self._token, method="answerCallbackQuery")
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        log.debug("Answering callback query - query_id=%s", callback_query_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def pin_chat_message(self, chat_id: str, message_id: int, disable_notification: bool = True) -> None:
        url = self._api_base.format(token=self._token, method="pinChatMessage")
        payload = {"chat_id": chat_id, "message_id": message_id}
        if disable_notification:
            payload["disable_notification"] = True
        log.debug("Pinning message - chat_id=%s, message_id=%s", chat_id, message_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def unpin_all_chat_messages(self, chat_id: str) -> None:
        url = self._api_base.format(token=self._token, method="unpinAllChatMessages")
        payload = {"chat_id": chat_id}
        log.debug("Unpinning all messages - chat_id=%s", chat_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()

    def get_file_path(self, file_id: str) -> str:
        url = self._api_base.format(token=self._token, method="getFile")
        payload = {"file_id": file_id}
        log.debug("Getting file path - file_id=%s", file_id)
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()["result"]["file_path"]

    def download_file(self, file_path: str) -> bytes:
        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        log.debug("Downloading file - file_path=%s", file_path)
        resp = self._client.get(url)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def format_message(row: dict) -> str:
        description = row.get('description', '').strip()
        message_link = row.get('tg_message_link', '').strip()
        channel_link = row.get('tg_channel_link', '').strip()
        matched_keywords = row.get('matched_keywords') or []

        if not description:
            raise ValueError(f"Message {row.get('id')} missing description")

        if isinstance(matched_keywords, str):
            try:
                matched_keywords = json.loads(matched_keywords)
            except (json.JSONDecodeError, TypeError):
                matched_keywords = []
        matched_keywords = matched_keywords or []

        text = f"{description}\n\n"

        if matched_keywords:
            text += f"🔑 {', '.join(matched_keywords)}\n\n"

        links = []
        if message_link:
            links.append(f'<a href="{message_link}">Message</a>')
        if channel_link:
            links.append(f'<a href="{channel_link}">Channel</a>')

        if links:
            text += " | ".join(links)

        return text
