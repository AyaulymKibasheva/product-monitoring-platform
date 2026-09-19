from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from src.models import Availability, Product
from src.monitoring import ChangePolicy, ChangeType, ProductSnapshot, detect_changes


def current_product() -> Product:
    return Product(
        organization_id="org",
        source_id="source",
        external_id="item",
        name="New name",
        category="New category",
        price=Decimal("80"),
        currency="USD",
        availability=Availability.OUT_OF_STOCK,
        url="https://example.test/item",
        collected_at=datetime.now(timezone.utc),
        brand="Brand",
        attributes={"color": "blue"},
    )


def test_detects_price_drop_and_percentage() -> None:
    previous = ProductSnapshot(
        name="New name",
        category="New category",
        brand="Brand",
        price=Decimal("100"),
        currency="USD",
        availability=Availability.IN_STOCK,
        attributes={"color": "blue"},
    )

    events = detect_changes(previous, current_product())

    price_event = next(item for item in events if item.change_type is ChangeType.PRICE_DROP)
    assert price_event.absolute_difference == Decimal("-20")
    assert price_event.percentage_change == Decimal("-20")
    assert any(item.change_type is ChangeType.OUT_OF_STOCK for item in events)


def test_detects_back_in_stock_and_metadata_changes() -> None:
    previous = ProductSnapshot(
        name="Old name",
        category="Old category",
        brand="Old brand",
        price=Decimal("80"),
        currency="EUR",
        availability=Availability.OUT_OF_STOCK,
        attributes={"color": "red"},
    )

    events = detect_changes(
        previous,
        replace(current_product(), availability=Availability.IN_STOCK),
    )
    types = {item.change_type for item in events}

    assert ChangeType.BACK_IN_STOCK in types
    assert ChangeType.CURRENCY_CHANGED in types
    assert ChangeType.NAME_CHANGED in types
    assert ChangeType.CATEGORY_CHANGED in types
    assert ChangeType.BRAND_CHANGED in types
    assert ChangeType.ATTRIBUTES_CHANGED in types


def test_change_policy_filters_small_price_changes_and_disabled_events() -> None:
    previous = ProductSnapshot(
        name="Old name",
        category="New category",
        brand="Brand",
        price=Decimal("100"),
        currency="USD",
        availability=Availability.IN_STOCK,
        attributes={"color": "blue"},
    )
    policy = ChangePolicy.from_mapping(
        {
            "minimum_price_change": 25,
            "minimum_price_change_percent": 10,
            "enabled_events": ["price_drop", "name_changed"],
        }
    )

    types = {item.change_type for item in detect_changes(previous, current_product(), policy)}

    assert ChangeType.PRICE_DROP not in types
    assert types == {ChangeType.NAME_CHANGED}
