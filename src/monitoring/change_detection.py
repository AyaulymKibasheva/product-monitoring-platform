"""Pure comparison logic for significant product changes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from src.models import Availability, Product


class ChangeType(StrEnum):
    NEW_PRODUCT = "new_product"
    NEW_SOURCE_LISTING = "new_source_listing"
    EXTERNAL_ID_CHANGED = "external_id_changed"
    PRICE_DROP = "price_drop"
    PRICE_INCREASE = "price_increase"
    CURRENCY_CHANGED = "currency_changed"
    OUT_OF_STOCK = "out_of_stock"
    BACK_IN_STOCK = "back_in_stock"
    AVAILABILITY_CHANGED = "availability_changed"
    NAME_CHANGED = "name_changed"
    CATEGORY_CHANGED = "category_changed"
    BRAND_CHANGED = "brand_changed"
    ATTRIBUTES_CHANGED = "attributes_changed"
    PRODUCT_MISSING = "product_missing"
    PRODUCT_REAPPEARED = "product_reappeared"


@dataclass(frozen=True, slots=True)
class ChangePolicy:
    """Organization/source rules defining which changes are significant."""

    minimum_price_change: Decimal = Decimal("0")
    minimum_price_change_percent: Decimal = Decimal("0")
    enabled_events: frozenset[ChangeType] | None = None

    @classmethod
    def from_mapping(cls, value: dict | None) -> ChangePolicy:
        value = value or {}
        raw_events = value.get("enabled_events")
        events = (
            frozenset(ChangeType(item) for item in raw_events)
            if raw_events is not None
            else None
        )
        minimum = Decimal(str(value.get("minimum_price_change", 0)))
        percentage = Decimal(str(value.get("minimum_price_change_percent", 0)))
        if minimum < 0 or percentage < 0:
            raise ValueError("monitoring price thresholds must be non-negative")
        return cls(minimum, percentage, events)

    def allows(self, event: ChangeEvent) -> bool:
        if self.enabled_events is not None and event.change_type not in self.enabled_events:
            return False
        if event.change_type in {ChangeType.PRICE_DROP, ChangeType.PRICE_INCREASE}:
            absolute = abs(event.absolute_difference or Decimal("0"))
            percentage = abs(event.percentage_change or Decimal("0"))
            return (
                absolute >= self.minimum_price_change
                and percentage >= self.minimum_price_change_percent
            )
        return True


@dataclass(frozen=True, slots=True)
class ProductSnapshot:
    name: str
    category: str | None
    brand: str | None
    price: Decimal
    currency: str
    availability: Availability
    attributes: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    change_type: ChangeType
    field: str
    old_value: str | None
    new_value: str | None
    absolute_difference: Decimal | None = None
    percentage_change: Decimal | None = None


def detect_changes(
    previous: ProductSnapshot,
    current: Product,
    policy: ChangePolicy | None = None,
) -> list[ChangeEvent]:
    events: list[ChangeEvent] = []
    if previous.price != current.price:
        difference = current.price - previous.price
        percentage = (
            (difference / previous.price * Decimal("100"))
            if previous.price != 0
            else None
        )
        events.append(
            ChangeEvent(
                ChangeType.PRICE_DROP if difference < 0 else ChangeType.PRICE_INCREASE,
                "price",
                str(previous.price),
                str(current.price),
                difference,
                percentage,
            )
        )
    if previous.currency != current.currency:
        events.append(
            ChangeEvent(
                ChangeType.CURRENCY_CHANGED,
                "currency",
                previous.currency,
                current.currency,
            )
        )
    if previous.availability != current.availability:
        if current.availability is Availability.OUT_OF_STOCK:
            change_type = ChangeType.OUT_OF_STOCK
        elif (
            previous.availability is Availability.OUT_OF_STOCK
            and current.availability is Availability.IN_STOCK
        ):
            change_type = ChangeType.BACK_IN_STOCK
        else:
            change_type = ChangeType.AVAILABILITY_CHANGED
        events.append(
            ChangeEvent(
                change_type,
                "availability",
                previous.availability.value,
                current.availability.value,
            )
        )
    _text_change(events, ChangeType.NAME_CHANGED, "name", previous.name, current.name)
    _text_change(
        events,
        ChangeType.CATEGORY_CHANGED,
        "category",
        previous.category,
        current.category,
    )
    _text_change(events, ChangeType.BRAND_CHANGED, "brand", previous.brand, current.brand)
    if _json(previous.attributes) != _json(current.attributes):
        events.append(
            ChangeEvent(
                ChangeType.ATTRIBUTES_CHANGED,
                "attributes",
                _json(previous.attributes),
                _json(current.attributes),
            )
        )
    active_policy = policy or ChangePolicy()
    return [event for event in events if active_policy.allows(event)]


def _text_change(
    events: list[ChangeEvent],
    change_type: ChangeType,
    field: str,
    old_value: str | None,
    new_value: str | None,
) -> None:
    if old_value != new_value:
        events.append(ChangeEvent(change_type, field, old_value, new_value))


def _json(value: dict[str, str] | None) -> str | None:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value else None
