import time
import logging
import httpx

log = logging.getLogger(__name__)


class TelegramSender:
    _api_base = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str, send_delay: float = 0.5) -> None:
        self._token = token
        self._chat_id = chat_id
        self._send_delay = send_delay
        self._client = httpx.Client(timeout=15)

    def send_message(self, text: str) -> None:
        url = self._api_base.format(token=self._token, method="sendMessage")
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}
        log.debug("Sending message - chat_id=%s, text_len=%d", self._chat_id, len(text))
        resp = self._client.post(url, json=payload)
        if resp.status_code != 200:
            log.error("Telegram API error: status=%d, response=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        time.sleep(self._send_delay)

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def format_message(row: dict) -> str:
        description = row.get('description', '').strip()
        message_link = row.get('tg_message_link', '').strip()
        channel_link = row.get('tg_channel_link', '').strip()

        if not description:
            raise ValueError(f"Message {row.get('id')} missing description")

        text = f"{description}\n\n"
        links = []
        if message_link:
            links.append(f'<a href="{message_link}">Message</a>')
        if channel_link:
            links.append(f'<a href="{channel_link}">Channel</a>')

        if links:
            text += " | ".join(links)

        return text
