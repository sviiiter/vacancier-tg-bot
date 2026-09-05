from datetime import datetime, timedelta


def is_trial_active(subscriber: dict, trial_type: str, message_limit: int, days_limit: int) -> bool:
    """
    Determine if a subscriber is still within their trial period.

    - Paid subscribers (plan != 'free') are always outside trial (return True).
    - Free subscribers are gated by trial_type: 'messages' or 'days'.
    """
    if subscriber["plan"] != "free":
        return True

    if trial_type == "days":
        subscribed_at = subscriber["subscribed_at"]
        if isinstance(subscribed_at, str):
            subscribed_at = datetime.fromisoformat(subscribed_at.replace("Z", "+00:00"))
        elapsed = datetime.now(subscribed_at.tzinfo) - subscribed_at if subscribed_at.tzinfo else datetime.now() - subscribed_at
        return elapsed < timedelta(days=days_limit)

    return subscriber["messages_received"] < message_limit
