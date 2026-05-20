from abc import ABC, abstractmethod


class DatabaseDriver(ABC):
    @abstractmethod
    def get_pending(self, limit: int) -> list[dict]:
        """Return up to `limit` messages where queue_sent=0 and read=0."""

    @abstractmethod
    def mark_sent(self, ids: list[int]) -> None:
        """Set queue_sent=1 for the given message IDs."""

    def close(self) -> None:
        pass
