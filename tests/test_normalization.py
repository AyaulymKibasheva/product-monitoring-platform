from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.models import Availability
from src.normalization import (
    normalize_availability,
    normalize_datetime,
    normalize_price,
    normalize_product,
    normalize_rating,
    normalize_text,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw", "expected", "currency"),
    [
        ("$1,299.99", Decimal("1299.99"), "USD"),
        ("1299.99 USD", Decimal("1299.99"), "USD"),
        ("1 299,99", Decimal("1299.99"), None),
        ("£51.77", Decimal("51.77"), "GBP"),
        ("1.299,99 EUR", Decimal("1299.99"), "EUR"),
    ],
)
def test_normalize_price_formats(raw, expected, currency) -> None:
    assert normalize_price(raw) == (expected, currency)


def test_normalize_common_values() -> None:
    assert normalize_text("  A\n  &amp; B  ") == "A & B"
    assert normalize_availability("Out of stock") is Availability.OUT_OF_STOCK
    assert normalize_availability("In stock (2)") is Availability.IN_STOCK
    assert normalize_availability(None) is Availability.UNKNOWN
    assert normalize_rating("4,5") == 4.5
    assert normalize_url("/Item?q=1#details", "HTTPS://Example.TEST/base/") == (
        "https://example.test/Item?q=1"
    )
    assert normalize_datetime("2026-01-01T03:00:00+03:00") == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )


def test_normalize_product_returns_canonical_model() -> None:
    product = normalize_product(
        organization_id=" Company A ",
        source_id=" SHOP.EXAMPLE ",
        external_id=" 42 ",
        name=" Product   name ",
        category="  science FICTION ",
        price="$1,299.99",
        currency=None,
        availability="available",
        rating="5",
        url="/products/42#top",
        base_url="https://SHOP.example/catalog/",
        collected_at="2026-01-01T00:00:00Z",
    )

    assert product.organization_id == "company a"
    assert product.external_id == "42"
    assert product.name == "Product name"
    assert product.category == "Science Fiction"
    assert product.price == Decimal("1299.99")
    assert product.currency == "USD"
    assert product.availability is Availability.IN_STOCK
    assert product.url == "https://shop.example/products/42"
    assert product.source_id == "shop.example"


def test_extended_product_fields_are_normalized() -> None:
    product = normalize_product(
        organization_id="org",
        source_id="supplier-api",
        external_id="x-1",
        sku=" SKU 1 ",
        name="Item",
        brand=" Brand ",
        category=None,
        description=" Description ",
        price="100 USD",
        old_price="120",
        currency=None,
        availability="pre-order",
        quantity="7",
        rating=None,
        review_count="12",
        url="https://example.test/x-1",
        image_url="/images/x-1.jpg",
        attributes={" Color ": " Blue "},
        base_url="https://example.test/",
    )

    assert product.sku == "SKU 1"
    assert product.brand == "Brand"
    assert product.old_price == Decimal("120")
    assert product.availability is Availability.PREORDER
    assert product.quantity == 7
    assert product.review_count == 12
    assert product.image_url == "https://example.test/images/x-1.jpg"
    assert product.attributes == {"Color": "Blue"}


@pytest.mark.parametrize("value", ["not-a-number", "-1", None])
def test_invalid_price_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        normalize_price(value)
