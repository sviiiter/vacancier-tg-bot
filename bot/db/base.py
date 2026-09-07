from abc import ABC, abstractmethod


class DatabaseDriver(ABC):
    @abstractmethod
    def add_subscriber(self, chat_id: str, username: str | None = None) -> None:
        """Add or reactivate a subscriber."""

    @abstractmethod
    def remove_subscriber(self, chat_id: str) -> None:
        """Deactivate a subscriber (soft delete)."""

    @abstractmethod
    def list_active_subscribers(self) -> list[str]:
        """Return list of active subscriber chat_ids."""

    @abstractmethod
    def get_last_update_id(self) -> int:
        """Get the last processed Telegram update_id."""

    @abstractmethod
    def set_last_update_id(self, update_id: int) -> None:
        """Save the last processed Telegram update_id."""

    @abstractmethod
    def record_payment(self, chat_id: str, plan: str, amount: int, charge_id: str, is_recurring: int) -> bool:
        """Record a payment; return False if charge_id already exists (idempotency)."""

    @abstractmethod
    def activate_paid_plan(self, chat_id: str, plan: str, expires_at: str, charge_id: str | None = None) -> None:
        """Activate a paid plan for a subscriber."""

    @abstractmethod
    def get_subscriber(self, chat_id: str) -> dict | None:
        """Fetch a single subscriber by chat_id."""

    @abstractmethod
    def downgrade_expired_subscribers(self) -> list[str]:
        """Downgrade expired subscribers to 'free' plan, return affected chat_ids."""

    @abstractmethod
    def get_messages_by_ids(self, ids: list[int]) -> list[dict]:
        """Fetch messages by IDs, ordered by created_date ASC."""

    @abstractmethod
    def update_message_sent_last_date(self, chat_id: str, ts) -> None:
        """Update message_sent_last_date for a subscriber, only if the new date is newer."""

    @abstractmethod
    def increment_messages_received(self, chat_ids: list[str]) -> None:
        """Increment messages_received count for the given chat_ids."""

    @abstractmethod
    def mark_trial_notice_sent(self, chat_id: str) -> None:
        """Mark trial notice as sent for a chat_id."""

    @abstractmethod
    def get_settings(self) -> dict:
        """Return the global bot settings (pricing, trial policy)."""

    @abstractmethod
    def get_subscriber_filters(self, chat_id: str) -> list[dict]:
        """Get all filters subscribed to by a subscriber."""

    @abstractmethod
    def update_message_sent_date(self, chat_id: str) -> None:
        """Update message_sent_last_date to now for a subscriber."""

    def rollback(self) -> None:
        """Roll back any pending transaction (default no-op)."""
        pass

    def close(self) -> None:
        pass
