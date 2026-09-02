import unittest
from unittest.mock import Mock, patch
from bot.sender import TelegramSender


class TestTelegramSender(unittest.TestCase):
    def test_format_message_simple(self) -> None:
        row = {
            "description": "Senior PHP Developer",
            "tg_message_link": "https://t.me/test/1",
            "tg_channel_link": "https://t.me/test_channel",
        }
        result = TelegramSender.format_message(row)
        self.assertIn("Senior PHP Developer", result)
        self.assertIn("t.me/test/1", result)
        self.assertIn("t.me/test_channel", result)

    def test_format_message_with_matched_keywords(self) -> None:
        row = {
            "description": "Senior PHP Developer",
            "tg_message_link": "https://t.me/test/1",
            "tg_channel_link": "https://t.me/test_channel",
            "matched_keywords": ["PHP", "Senior"],
        }
        result = TelegramSender.format_message(row)
        self.assertIn("🔑", result)
        self.assertIn("PHP", result)
        self.assertIn("Senior", result)

    def test_format_message_missing_description(self) -> None:
        row = {
            "description": "",
            "tg_message_link": "https://t.me/test/1",
            "tg_channel_link": "https://t.me/test_channel",
        }
        with self.assertRaises(ValueError):
            TelegramSender.format_message(row)

    @patch("bot.sender.httpx.Client.post")
    def test_send_message(self, mock_post) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        sender = TelegramSender("fake_token", send_delay=0)
        sender.send_message("Test message", "123456")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("sendMessage", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["chat_id"], "123456")
        self.assertEqual(call_args[1]["json"]["text"], "Test message")
        self.assertEqual(call_args[1]["json"]["parse_mode"], "HTML")
