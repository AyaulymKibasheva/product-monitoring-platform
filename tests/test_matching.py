from datetime import datetime, timezone
from decimal import Decimal

from src.matching import MatchCandidate, ProductMatcher
from src.models import Availability, Product


def incoming(**changes) -> Product:
    values = {
        "organization_id": "org",
        "source_id": "source-b",
        "external_id": "external-b",
        "name": "Coffee Beans 1 kg",
        "category": "Coffee",
        "price": Decimal("20"),
        "currency": "USD",
        "availability": Availability.IN_STOCK,
        "url": "https://b.example/item",
        "collected_at": datetime.now(timezone.utc),
        "sku": "SKU-42",
        "brand": "Acme",
    }
    values.update(changes)
    return Product(**values)


def candidate(**changes) -> MatchCandidate:
    values = {
        "product_id": 7,
        "organization_id": "org",
        "name": "Coffee Beans 1 kg",
        "sku": "SKU-42",
        "brand": "Acme",
        "url": "https://a.example/product",
        "attributes": None,
    }
    values.update(changes)
    return MatchCandidate(**values)


def test_exact_sku_is_safe_to_auto_merge() -> None:
    decision = ProductMatcher().compare(incoming(), candidate())

    assert decision.auto_merge is True
    assert decision.score == 0.98
    assert decision.reason == "sku"


def test_global_identifier_has_highest_confidence() -> None:
    decision = ProductMatcher().compare(
        incoming(sku=None, attributes={"GTIN": "123456789"}),
        candidate(sku=None, attributes={"ean": "123456789"}),
    )

    assert decision.auto_merge is True
    assert decision.score == 1.0


def test_same_name_is_not_enough_to_merge() -> None:
    decision = ProductMatcher().compare(
        incoming(sku=None, brand=None),
        candidate(sku=None, brand=None),
    )

    assert decision.auto_merge is False
    assert decision.reason == "name_only"


def test_different_skus_keep_variants_separate() -> None:
    decision = ProductMatcher().compare(
        incoming(sku="SIZE-S"),
        candidate(sku="SIZE-L"),
    )

    assert decision.auto_merge is False
    assert decision.reason == "different_sku"

