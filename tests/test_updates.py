import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from bot.updates import UpdateHandler
from bot.db.base import DatabaseDriver
from bot.sender import TelegramSender


class TestUpdateHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_client = Mock()
        self.handler = UpdateHandler("fake_token", self.mock_client)
        self.mock_driver = Mock(spec=DatabaseDriver)
        self.mock_sender = Mock(spec=TelegramSender)

    def test_handle_upgrade_command(self) -> None:
        update = {
            "update_id": 1,
            "message": {
                "chat": {"id": 123456},
                "from": {"username": "testuser"},
                "text": "/upgrade",
            },
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_sender.send_menu.assert_called_once()
        call_args = self.mock_sender.send_menu.call_args
        self.assertEqual(call_args[0][0], "123456")
        self.assertEqual(len(call_args[0][2]), 2)

    def test_handle_callback_query_monthly(self) -> None:
        update = {
            "callback_query": {
                "id": "query_1",
                "from": {"id": 123456},
                "data": "buy:monthly",
            }
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_sender.send_invoice.assert_called_once()
        call_args = self.mock_sender.send_invoice.call_args
        self.assertEqual(call_args[0][0], "123456")
        self.assertIn("Monthly", call_args[0][1])
        self.assertEqual(call_args[1]["subscription_period"], 2592000)

    def test_handle_callback_query_yearly(self) -> None:
        update = {
            "callback_query": {
                "id": "query_1",
                "from": {"id": 123456},
                "data": "buy:yearly",
            }
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        call_args = self.mock_sender.send_invoice.call_args
        self.assertIn("Yearly", call_args[0][1])
        self.assertIsNone(call_args[1]["subscription_period"])

    def test_handle_pre_checkout_query(self) -> None:
        update = {
            "pre_checkout_query": {
                "id": "query_1",
                "from": {"id": 123456},
                "invoice_payload": "123456:monthly",
            }
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_sender.answer_pre_checkout_query.assert_called_once_with("query_1", ok=True)

    def test_handle_successful_payment_monthly(self) -> None:
        update = {
            "message": {
                "chat": {"id": 123456},
                "successful_payment": {
                    "telegram_payment_charge_id": "charge_123",
                    "invoice_payload": "123456:monthly",
                    "total_amount": 100,
                },
            }
        }
        self.mock_driver.record_payment.return_value = True
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_driver.record_payment.assert_called_once()
        self.mock_driver.activate_paid_plan.assert_called_once()
        call_args = self.mock_driver.activate_paid_plan.call_args
        self.assertEqual(call_args[0][0], "123456")
        self.assertEqual(call_args[0][1], "monthly")

    def test_handle_successful_payment_yearly(self) -> None:
        update = {
            "message": {
                "chat": {"id": 123456},
                "successful_payment": {
                    "telegram_payment_charge_id": "charge_123",
                    "invoice_payload": "123456:yearly",
                    "total_amount": 1000,
                },
            }
        }
        self.mock_driver.record_payment.return_value = True
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        call_args = self.mock_driver.activate_paid_plan.call_args
        self.assertEqual(call_args[0][1], "yearly")

    def test_handle_successful_payment_idempotency(self) -> None:
        update = {
            "message": {
                "chat": {"id": 123456},
                "successful_payment": {
                    "telegram_payment_charge_id": "charge_123",
                    "invoice_payload": "123456:monthly",
                    "total_amount": 100,
                },
            }
        }
        self.mock_driver.record_payment.return_value = False
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_driver.activate_paid_plan.assert_not_called()

    def test_handle_cancel_command_with_active_subscription(self) -> None:
        self.mock_driver.get_subscriber.return_value = {
            "chat_id": "123456",
            "plan": "monthly",
            "star_charge_id": "charge_123",
        }
        update = {
            "message": {
                "chat": {"id": 123456},
                "from": {"username": "testuser"},
                "text": "/cancel",
            }
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_sender.cancel_star_subscription.assert_called_once_with("123456", "charge_123")

    def test_handle_cancel_command_no_subscription(self) -> None:
        self.mock_driver.get_subscriber.return_value = {
            "chat_id": "123456",
            "plan": "free",
            "star_charge_id": None,
        }
        update = {
            "message": {
                "chat": {"id": 123456},
                "from": {"username": "testuser"},
                "text": "/cancel",
            }
        }
        self.handler.handle_update(update, self.mock_driver, self.mock_sender)
        self.mock_sender.cancel_star_subscription.assert_not_called()
