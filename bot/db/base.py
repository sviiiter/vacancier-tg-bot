from abc import ABC, abstractmethod


class DatabaseDriver(ABC):
    @abstractmethod
    def get_pending(self, limit: int) -> list[dict]:
        """Return up to `limit` messages where queue_sent=0 and read=0."""

    @abstractmethod
    def mark_sent(self, ids: list[int]) -> None:
        """Set queue_sent=1 for the given message IDs."""

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

    def close(self) -> None:
        pass
