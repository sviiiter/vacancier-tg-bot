import unittest
import tempfile
import os
from datetime import datetime, timedelta
from bot.db.sqlite import SQLiteDriver


class TestSQLiteDriver(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_file.close()
        self.driver = SQLiteDriver(self.temp_file.name)

    def tearDown(self) -> None:
        self.driver.close()
        os.unlink(self.temp_file.name)

    def test_add_subscriber(self) -> None:
        self.driver.add_subscriber("123456", "testuser")
        subscribers = self.driver.list_active_subscribers()
        self.assertIn("123456", subscribers)

    def test_remove_subscriber(self) -> None:
        self.driver.add_subscriber("123456", "testuser")
        self.driver.remove_subscriber("123456")
        subscribers = self.driver.list_active_subscribers()
        self.assertNotIn("123456", subscribers)

    def test_reactivate_subscriber(self) -> None:
        self.driver.add_subscriber("123456", "testuser")
        self.driver.remove_subscriber("123456")
        self.driver.add_subscriber("123456", "testuser")
        subscribers = self.driver.list_active_subscribers()
        self.assertIn("123456", subscribers)

    def test_last_update_id_persistence(self) -> None:
        self.assertEqual(self.driver.get_last_update_id(), 0)
        self.driver.set_last_update_id(42)
        self.assertEqual(self.driver.get_last_update_id(), 42)
        self.driver.set_last_update_id(100)
        self.assertEqual(self.driver.get_last_update_id(), 100)

    def test_multiple_subscribers(self) -> None:
        self.driver.add_subscriber("111111", "user1")
        self.driver.add_subscriber("222222", "user2")
        self.driver.add_subscriber("333333", "user3")
        subscribers = self.driver.list_active_subscribers()
        self.assertEqual(len(subscribers), 3)
        self.assertIn("111111", subscribers)
        self.assertIn("222222", subscribers)
        self.assertIn("333333", subscribers)

    def test_record_payment(self) -> None:
        result = self.driver.record_payment("123456", "monthly", 100, "charge_123", 1)
        self.assertTrue(result)
        result2 = self.driver.record_payment("123456", "monthly", 100, "charge_123", 1)
        self.assertFalse(result2)

    def test_activate_paid_plan(self) -> None:
        self.driver.add_subscriber("123456", "testuser")
        expires_at = (datetime.now() + timedelta(days=30)).isoformat()
        self.driver.activate_paid_plan("123456", "monthly", expires_at, "charge_123")
        sub = self.driver.get_subscriber("123456")
        self.assertIsNotNone(sub)
        self.assertEqual(sub["plan"], "monthly")
        self.assertEqual(sub["star_charge_id"], "charge_123")

    def test_get_subscriber(self) -> None:
        self.driver.add_subscriber("123456", "testuser")
        sub = self.driver.get_subscriber("123456")
        self.assertIsNotNone(sub)
        self.assertEqual(sub["chat_id"], "123456")
        self.assertEqual(sub["username"], "testuser")
        self.assertEqual(sub["plan"], "free")

    def test_downgrade_expired_subscribers(self) -> None:
        self.driver.add_subscriber("111111", "user1")
        self.driver.add_subscriber("222222", "user2")
        past = (datetime.now() - timedelta(days=1)).isoformat()
        future = (datetime.now() + timedelta(days=30)).isoformat()
        self.driver.activate_paid_plan("111111", "monthly", past, "charge_111")
        self.driver.activate_paid_plan("222222", "monthly", future, "charge_222")
        expired = self.driver.downgrade_expired_subscribers()
        self.assertIn("111111", expired)
        self.assertNotIn("222222", expired)
        sub1 = self.driver.get_subscriber("111111")
        self.assertEqual(sub1["plan"], "free")
        sub2 = self.driver.get_subscriber("222222")
        self.assertEqual(sub2["plan"], "monthly")
