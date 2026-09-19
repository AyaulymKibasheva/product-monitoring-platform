"""Rule matching, de-duplication, scheduling, and retry delivery."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.database.models import (
    NotificationChannelRow,
    NotificationDeliveryRow,
    NotificationRuleRow,
    OrganizationRow,
    ProductChangeEventRow,
    ProductRow,
    ScrapeErrorRow,
    ScrapeRunRow,
    SourceRow,
)

from .channels import NotificationChannel, NotificationMessage, build_channel

LOGGER = logging.getLogger(__name__)
ChannelFactory = Callable[[str, str | None, dict[str, Any]], NotificationChannel]


class NotificationDispatcher:
    def __init__(
        self,
        engine: Engine,
        *,
        channel_factory: ChannelFactory = build_channel,
        max_attempts: int = 3,
    ) -> None:
        self.engine = engine
        self.channel_factory = channel_factory
        self.max_attempts = max_attempts

    def process_run(self, run_id: int) -> int:
        """Create matching deliveries for a run and send those due now."""
        now = datetime.now(timezone.utc)
        with Session(self.engine) as session, session.begin():
            run = session.get(ScrapeRunRow, run_id)
            if run is None:
                raise ValueError(f"unknown scrape run: {run_id}")
            source = session.get(SourceRow, run.source_id)
            if source is None:
                raise ValueError(f"run {run_id} references unknown source")
            rules = session.scalars(
                select(NotificationRuleRow).where(
                    NotificationRuleRow.organization_id == source.organization_id,
                    NotificationRuleRow.active.is_(True),
                )
            ).all()
            channels = session.scalars(
                select(NotificationChannelRow).where(
                    NotificationChannelRow.organization_id == source.organization_id,
                    NotificationChannelRow.active.is_(True),
                )
            ).all()
            events = self._events(session, run, source)
            for event_key, event_type, payload in events:
                for rule in rules:
                    if not self._matches(rule, event_type, payload):
                        continue
                    allowed = set(rule.channel_ids or [])
                    for channel in channels:
                        if allowed and channel.channel_id not in allowed:
                            continue
                        exists = session.scalar(
                            select(NotificationDeliveryRow.delivery_id).where(
                                NotificationDeliveryRow.event_key == event_key,
                                NotificationDeliveryRow.rule_id == rule.rule_id,
                                NotificationDeliveryRow.channel_id == channel.channel_id,
                            )
                        )
                        if exists is None:
                            session.add(
                                NotificationDeliveryRow(
                                    event_key=event_key,
                                    run_id=run_id,
                                    rule_id=rule.rule_id,
                                    channel_id=channel.channel_id,
                                    event_type=event_type,
                                    payload=payload,
                                    status="pending",
                                    attempts=0,
                                    next_attempt_at=self._scheduled_at(rule.frequency, now),
                                    created_at=now,
                                )
                            )
        return self.dispatch_pending(now=now)

    def dispatch_pending(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        sent = 0
        with Session(self.engine) as session:
            deliveries = session.scalars(
                select(NotificationDeliveryRow)
                .where(
                    NotificationDeliveryRow.status.in_(("pending", "retry")),
                    NotificationDeliveryRow.next_attempt_at <= now,
                )
                .order_by(NotificationDeliveryRow.created_at)
            ).all()
            for delivery in deliveries:
                channel = session.get(NotificationChannelRow, delivery.channel_id)
                rule = session.get(NotificationRuleRow, delivery.rule_id)
                if channel is None or rule is None or not channel.active or not rule.active:
                    delivery.status = "cancelled"
                    session.commit()
                    continue
                delivery.attempts += 1
                try:
                    adapter = self.channel_factory(
                        channel.channel_type, channel.recipient, channel.settings or {}
                    )
                    adapter.send(self._message(rule.name, delivery.event_type, delivery.payload))
                except Exception as exc:  # delivery failures must not stop collection
                    delivery.last_error = str(exc)[:4000]
                    if delivery.attempts >= self.max_attempts:
                        delivery.status = "failed"
                    else:
                        delivery.status = "retry"
                        delivery.next_attempt_at = now + timedelta(
                            minutes=2 ** (delivery.attempts - 1)
                        )
                    LOGGER.warning("Notification delivery %s failed: %s", delivery.delivery_id, exc)
                else:
                    delivery.status = "sent"
                    delivery.sent_at = now
                    delivery.last_error = None
                    sent += 1
                session.commit()
        return sent

    @staticmethod
    def _events(
        session: Session, run: ScrapeRunRow, source: SourceRow
    ) -> list[tuple[str, str, dict[str, Any]]]:
        organization = session.get(OrganizationRow, source.organization_id)
        base = {
            "run_id": run.run_id,
            "source_id": source.source_id,
            "source_name": source.name,
            "organization_id": source.organization_id,
            "organization_name": organization.name if organization else source.organization_id,
            "observed_at": (run.finished_at or run.started_at).isoformat(),
        }
        result: list[tuple[str, str, dict[str, Any]]] = []
        changes = session.execute(
            select(ProductChangeEventRow, ProductRow)
            .join(ProductRow, ProductRow.product_id == ProductChangeEventRow.product_id)
            .where(ProductChangeEventRow.run_id == run.run_id)
        ).all()
        for change, product in changes:
            payload = {
                **base,
                "product_id": product.product_id,
                "external_id": change.external_id,
                "product_name": product.name,
                "brand": product.brand,
                "category": product.category,
                "url": product.url,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "percentage_change": (
                    float(change.percentage_change)
                    if change.percentage_change is not None
                    else None
                ),
            }
            result.append((f"change:{change.event_id}", change.change_type, payload))
        if run.status == "failed":
            error = session.scalar(
                select(ScrapeErrorRow.message)
                .where(ScrapeErrorRow.run_id == run.run_id)
                .order_by(ScrapeErrorRow.error_id)
            )
            result.append(
                (f"run:{run.run_id}:source_failed", "source_failed", {**base, "error": error})
            )
        validation_errors = session.scalar(
            select(ScrapeErrorRow.error_id).where(
                ScrapeErrorRow.run_id == run.run_id,
                ScrapeErrorRow.stage == "validation",
            )
        )
        if validation_errors is not None:
            result.append(
                (
                    f"run:{run.run_id}:data_quality_problem",
                    "data_quality_problem",
                    {**base, "rejected_records": run.records_rejected},
                )
            )
        return result

    @staticmethod
    def _matches(rule: NotificationRuleRow, event_type: str, payload: dict[str, Any]) -> bool:
        if rule.event_types and event_type not in rule.event_types:
            return False
        if rule.source_ids and payload["source_id"] not in rule.source_ids:
            return False
        if rule.categories and payload.get("category") not in rule.categories:
            return False
        if rule.brands and payload.get("brand") not in rule.brands:
            return False
        if event_type in {"price_drop", "price_increase"}:
            percentage = abs(Decimal(str(payload.get("percentage_change") or 0)))
            if percentage < rule.minimum_price_change_percent:
                return False
        return True

    @staticmethod
    def _scheduled_at(frequency: str, now: datetime) -> datetime:
        if frequency == "hourly":
            return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if frequency == "daily":
            return (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        return now

    @staticmethod
    def _message(rule_name: str, event_type: str, payload: dict[str, Any]) -> NotificationMessage:
        label = event_type.replace("_", " ").upper()
        subject = f"[{label}] {payload.get('product_name') or payload['source_name']}"
        lines = [
            f"Rule: {rule_name}",
            f"Organization: {payload['organization_name']}",
            f"Source: {payload['source_name']}",
            f"Event: {label}",
        ]
        if payload.get("product_name"):
            lines.append(f"Product: {payload['product_name']}")
        if payload.get("old_value") is not None or payload.get("new_value") is not None:
            lines.append(f"Change: {payload.get('old_value')} -> {payload.get('new_value')}")
        if payload.get("percentage_change") is not None:
            lines.append(f"Change percent: {payload['percentage_change']:.2f}%")
        if payload.get("error"):
            lines.append(f"Error: {payload['error']}")
        if payload.get("url"):
            lines.append(f"URL: {payload['url']}")
        lines.append(f"Observed at: {payload['observed_at']}")
        return NotificationMessage(subject, "\n".join(lines))
