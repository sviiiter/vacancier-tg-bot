import unittest
import tempfile
import os
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
