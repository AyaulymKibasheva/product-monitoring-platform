from decimal import Decimal

import responses

from src.models import Availability
from src.sources.api.dummyjson import DummyJsonSource


def api_product(product_id: int) -> dict:
    return {
        "id": product_id,
        "title": f"Product {product_id}",
        "description": "Description",
        "category": "beauty",
        "price": 80,
        "discountPercentage": 20,
        "rating": 4.5,
        "stock": 7,
        "availabilityStatus": "Low Stock",
        "brand": "Acme",
        "sku": f"SKU-{product_id}",
        "thumbnail": f"https://cdn.example/{product_id}.png",
        "reviews": [{"rating": 5}, {"rating": 4}],
        "meta": {"barcode": f"000{product_id}"},
        "weight": 3,
        "dimensions": {"width": 1, "height": 2, "depth": 3},
    }


@responses.activate
def test_collects_and_normalizes_paginated_api_products() -> None:
    responses.get(
        "https://api.example/products",
        json={"products": [api_product(1), api_product(2)], "total": 3},
    )
    responses.get(
        "https://api.example/products",
        json={"products": [api_product(3)], "total": 3},
    )
    source = DummyJsonSource(
        organization_id="org",
        source_id="api",
        base_url="https://api.example/",
        page_size=2,
    )

    result = source.collect()

    assert len(result.products) == 3
    first = result.products[0]
    assert first.price == Decimal("80")
    assert first.old_price == Decimal("100")
    assert first.availability is Availability.IN_STOCK
    assert first.quantity == 7
    assert first.review_count == 2
    assert first.attributes["gtin"] == "0001"
    assert result.stats.pages_fetched == 2
    assert result.stats.complete_snapshot is True


@responses.activate
def test_api_page_limit_marks_snapshot_incomplete() -> None:
    responses.get(
        "https://api.example/products",
        json={"products": [api_product(1)], "total": 3},
    )
    source = DummyJsonSource(
        organization_id="org",
        source_id="api",
        base_url="https://api.example/",
        page_size=1,
    )

    result = source.collect(max_pages=1)

    assert len(result.products) == 1
    assert result.stats.complete_snapshot is False


@responses.activate
def test_bad_api_record_is_skipped_without_stopping_page() -> None:
    responses.get(
        "https://api.example/products",
        json={"products": [{"id": "bad"}, api_product(2)], "total": 2},
    )
    source = DummyJsonSource(
        organization_id="org",
        source_id="api",
        base_url="https://api.example/",
    )

    result = source.collect()

    assert len(result.products) == 1
    assert result.stats.records_skipped == 1
    assert result.stats.errors

