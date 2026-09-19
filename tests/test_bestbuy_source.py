from decimal import Decimal

import pytest
import responses

from src.models import Availability
from src.sources.api.bestbuy import BestBuySource


def product(sku: int) -> dict:
    return {
        "sku": sku,
        "name": f"Laptop {sku}",
        "manufacturer": "Acme",
        "categoryPath": [{"name": "Computers"}, {"name": "Laptops"}],
        "salePrice": 899.99,
        "regularPrice": 999.99,
        "onSale": True,
        "onlineAvailability": True,
        "url": f"https://www.bestbuy.com/site/{sku}.p",
        "image": f"https://images.example/{sku}.jpg",
        "customerReviewAverage": 4.6,
        "customerReviewCount": 125,
        "shortDescription": "A real retail product",
        "upc": f"0000{sku}",
        "modelNumber": f"MODEL-{sku}",
        "color": "Blue",
    }


@responses.activate
def test_collects_bestbuy_products(monkeypatch) -> None:
    monkeypatch.setenv("BESTBUY_API_KEY", "test-key")
    responses.get(
        "https://api.bestbuy.test/v1/products((onlineAvailability=true))",
        json={"products": [product(101)], "totalPages": 1},
    )
    source = BestBuySource(
        organization_id="org", source_id="bestbuy", base_url="https://api.bestbuy.test/v1/"
    )
    result = source.collect()
    item = result.products[0]
    assert item.external_id == "101"
    assert item.price == Decimal("899.99")
    assert item.old_price == Decimal("999.99")
    assert item.category == "Laptops"
    assert item.availability is Availability.IN_STOCK
    assert item.attributes["upc"] == "0000101"
    assert result.stats.complete_snapshot is True


def test_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("BESTBUY_API_KEY", raising=False)
    source = BestBuySource(organization_id="org", source_id="bestbuy")
    with pytest.raises(RuntimeError, match="BESTBUY_API_KEY"):
        source.collect(max_pages=1)


@responses.activate
def test_page_limit_is_not_a_complete_snapshot(monkeypatch) -> None:
    monkeypatch.setenv("CUSTOM_BESTBUY_KEY", "test-key")
    responses.get(
        "https://api.bestbuy.test/v1/products((onlineAvailability=true))",
        json={"products": [product(101)], "totalPages": 2},
    )
    source = BestBuySource(
        organization_id="org",
        source_id="bestbuy",
        base_url="https://api.bestbuy.test/v1/",
        api_key_env="CUSTOM_BESTBUY_KEY",
    )
    result = source.collect(max_pages=1)
    assert result.stats.pages_fetched == 1
    assert result.stats.complete_snapshot is False
