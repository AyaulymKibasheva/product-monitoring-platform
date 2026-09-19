"""Organization-aware notification rules and delivery channels."""

from .channels import EmailChannel, NotificationMessage, SlackChannel
from .dispatcher import NotificationDispatcher

__all__ = ["EmailChannel", "NotificationDispatcher", "NotificationMessage", "SlackChannel"]
