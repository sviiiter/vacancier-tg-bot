import unittest
from datetime import datetime, timedelta
from bot.trial import is_trial_active


class TestTrialLogic(unittest.TestCase):
    def test_paid_subscriber_always_active(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "monthly",
            "messages_received": 100,
            "subscribed_at": datetime.now() - timedelta(days=10),
            "trial_notice_sent": 0,
        }
        self.assertTrue(is_trial_active(sub, "messages", 10, 2))
        self.assertTrue(is_trial_active(sub, "days", 10, 2))

    def test_free_trial_messages_active_below_limit(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 5,
            "subscribed_at": datetime.now(),
            "trial_notice_sent": 0,
        }
        self.assertTrue(is_trial_active(sub, "messages", 10, 2))

    def test_free_trial_messages_inactive_at_limit(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 10,
            "subscribed_at": datetime.now(),
            "trial_notice_sent": 0,
        }
        self.assertFalse(is_trial_active(sub, "messages", 10, 2))

    def test_free_trial_messages_inactive_above_limit(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 15,
            "subscribed_at": datetime.now(),
            "trial_notice_sent": 0,
        }
        self.assertFalse(is_trial_active(sub, "messages", 10, 2))

    def test_free_trial_days_active_within_window(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 100,
            "subscribed_at": datetime.now() - timedelta(hours=6),
            "trial_notice_sent": 0,
        }
        self.assertTrue(is_trial_active(sub, "days", 10, 2))

    def test_free_trial_days_inactive_at_limit(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 100,
            "subscribed_at": datetime.now() - timedelta(days=2),
            "trial_notice_sent": 0,
        }
        self.assertFalse(is_trial_active(sub, "days", 10, 2))

    def test_free_trial_days_inactive_past_limit(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 100,
            "subscribed_at": datetime.now() - timedelta(days=5),
            "trial_notice_sent": 0,
        }
        self.assertFalse(is_trial_active(sub, "days", 10, 2))

    def test_iso_format_subscribed_at(self) -> None:
        sub = {
            "chat_id": "123456",
            "plan": "free",
            "messages_received": 100,
            "subscribed_at": (datetime.now() - timedelta(hours=1)).isoformat(),
            "trial_notice_sent": 0,
        }
        self.assertTrue(is_trial_active(sub, "days", 10, 2))
