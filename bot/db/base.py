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

    @abstractmethod
    def create_filter(self, name: str, filter_type: str, extra: str | None = None, file_id: int | None = None) -> int:
        """Create a new filter. Returns the new filter id."""

    @abstractmethod
    def link_subscriber_to_filter(self, chat_id: str, filter_id: int) -> None:
        """Link a subscriber to an existing filter (idempotent)."""

    @abstractmethod
    def unlink_subscriber_filter(self, chat_id: str, filter_id: int) -> None:
        """Unlink a subscriber from a filter (never deletes the filter itself)."""

    @abstractmethod
    def unlink_all_subscriber_filters(self, chat_id: str) -> int:
        """Unlink a subscriber from all filters. Returns count of rows deleted."""

    @abstractmethod
    def list_filter_library(self) -> list[dict]:
        """List all filters in the system (id, name, type, extra, file_id), newest first."""

    @abstractmethod
    def get_known_keywords(self) -> list[str]:
        """Return deduplicated, sorted list of all keywords used across all filters."""

    @abstractmethod
    def get_file_name(self, file_id: int) -> str | None:
        """Get the filename for a file_id, or None if not found."""

    @abstractmethod
    def insert_file(self, filename: str, content: str) -> int:
        """Insert a file (content must be base64-encoded text). Returns new file id."""

    @abstractmethod
    def get_filter_preview(self, rules: dict, limit: int = 3) -> dict:
        """Get live preview of messages matching a filter's rules. Returns {'count': int, 'samples': []}."""

    def rollback(self) -> None:
        """Roll back any pending transaction (default no-op)."""
        pass

    def close(self) -> None:
        pass
