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

    @patch("bot.sender.httpx.Client.post")
    def test_send_invoice_monthly(self, mock_post) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        sender = TelegramSender("fake_token", send_delay=0)
        sender.send_invoice("123456", "Monthly", "30 days", "123456:monthly", 100, subscription_period=2592000)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("sendInvoice", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["chat_id"], "123456")
        self.assertEqual(call_args[1]["json"]["currency"], "XTR")
        self.assertEqual(call_args[1]["json"]["subscription_period"], 2592000)

    @patch("bot.sender.httpx.Client.post")
    def test_send_invoice_yearly(self, mock_post) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        sender = TelegramSender("fake_token", send_delay=0)
        sender.send_invoice("123456", "Yearly", "365 days", "123456:yearly", 1000, subscription_period=None)

        call_args = mock_post.call_args
        self.assertNotIn("subscription_period", call_args[1]["json"])

    @patch("bot.sender.httpx.Client.post")
    def test_answer_pre_checkout_query(self, mock_post) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        sender = TelegramSender("fake_token", send_delay=0)
        sender.answer_pre_checkout_query("query_123", ok=True)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("answerPreCheckoutQuery", call_args[0][0])
        self.assertEqual(call_args[1]["json"]["pre_checkout_query_id"], "query_123")
        self.assertTrue(call_args[1]["json"]["ok"])

    @patch("bot.sender.httpx.Client.post")
    def test_send_menu(self, mock_post) -> None:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        sender = TelegramSender("fake_token", send_delay=0)
        buttons = [("Monthly ⭐100", "buy:monthly"), ("Yearly ⭐1000", "buy:yearly")]
        sender.send_menu("123456", "Choose a plan:", buttons)

        call_args = mock_post.call_args
        self.assertEqual(len(call_args[1]["json"]["reply_markup"]["inline_keyboard"]), 2)
