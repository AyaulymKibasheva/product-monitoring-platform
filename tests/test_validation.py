from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from src.models import Availability, Product
from src.validation import ProductValidator


def valid_product(external_id: str = "item-1") -> Product:
    return Product(
        organization_id="org",
        source_id="source",
        external_id=external_id,
        name="Product",
        category="Category",
        price=Decimal("10.00"),
        currency="USD",
        availability=Availability.IN_STOCK,
        url=f"https://example.test/{external_id}",
        collected_at=datetime.now(timezone.utc),
        quantity=3,
        rating=4.5,
    )


def test_valid_batch_is_accepted() -> None:
    result = ProductValidator().validate_batch([valid_product()])

    assert result.total_received == 1
    assert result.accepted_count == 1
    assert result.rejected_count == 0


def test_bad_record_is_rejected_without_stopping_batch() -> None:
    bad = replace(
        valid_product("bad"),
        name="",
        price=Decimal("-1"),
        currency="dollars",
        url="not-a-url",
        rating=7,
        quantity=-1,
        collected_at=datetime(2026, 1, 1),
    )
    good = valid_product("good")

    result = ProductValidator().validate_batch([bad, good])

    assert result.accepted_count == 1
    assert result.valid_products == [good]
    assert result.rejected_count == 1
    assert {issue.field for issue in result.rejected_products[0].issues} == {
        "name",
        "price",
        "currency",
        "url",
        "rating",
        "quantity",
        "collected_at",
    }


def test_duplicate_identity_is_rejected() -> None:
    original = valid_product()
    duplicate = replace(original, name="Updated title")

    result = ProductValidator().validate_batch([original, duplicate])

    assert result.accepted_count == 1
    assert result.rejected_count == 1
    assert result.duplicate_count == 1
    assert result.rejected_products[0].issues[0].code == "duplicate"
