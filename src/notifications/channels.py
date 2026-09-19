"""Delivery adapters for organization notification channels."""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import requests


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    subject: str
    body: str


class NotificationChannel(Protocol):
    def send(self, message: NotificationMessage) -> None: ...


def _environment(settings: dict[str, Any], key: str, default: str) -> str:
    variable = str(settings.get(key, default))
    value = os.getenv(variable)
    if not value:
        raise RuntimeError(f"required environment variable {variable!r} is not set")
    return value


class EmailChannel:
    def __init__(self, recipient: str | None, settings: dict[str, Any]) -> None:
        if not recipient:
            raise ValueError("email notification channel requires a recipient")
        self.recipient = recipient
        self.settings = settings

    def send(self, message: NotificationMessage) -> None:
        host = _environment(self.settings, "host_env", "SMTP_HOST")
        sender = _environment(self.settings, "sender_env", "SMTP_FROM")
        port = int(os.getenv(str(self.settings.get("port_env", "SMTP_PORT")), "587"))
        username = os.getenv(str(self.settings.get("username_env", "SMTP_USERNAME")))
        password = os.getenv(str(self.settings.get("password_env", "SMTP_PASSWORD")))
        email = EmailMessage()
        email["From"] = sender
        email["To"] = self.recipient
        email["Subject"] = message.subject
        email.set_content(message.body)
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if bool(self.settings.get("starttls", True)):
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(email)


class SlackChannel:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    def send(self, message: NotificationMessage) -> None:
        webhook = _environment(self.settings, "webhook_env", "SLACK_WEBHOOK_URL")
        response = requests.post(
            webhook,
            json={"text": f"*{message.subject}*\n{message.body}"},
            timeout=20,
        )
        response.raise_for_status()


def build_channel(
    channel_type: str, recipient: str | None, settings: dict[str, Any]
) -> NotificationChannel:
    if channel_type == "email":
        return EmailChannel(recipient, settings)
    if channel_type == "slack":
        return SlackChannel(settings)
    raise ValueError(f"unsupported notification channel: {channel_type}")
