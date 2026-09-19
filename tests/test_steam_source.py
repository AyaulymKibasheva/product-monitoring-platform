from decimal import Decimal

import responses

from src.models import Availability
from src.sources.api.steam import SteamStoreSource


def game(app_id: int, price: int = 4199) -> dict:
    return {
        "id": app_id,
        "name": f"Game {app_id}",
        "currency": "USD",
        "original_price": 5999,
        "final_price": price,
        "discount_percent": 30,
        "large_capsule_image": f"https://cdn.example/{app_id}.jpg",
        "windows_available": True,
        "mac_available": False,
        "linux_available": True,
        "controller_support": "full",
    }


@responses.activate
def test_collects_live_store_sections_and_deduplicates() -> None:
    responses.get(
        "https://store.example/api/featuredcategories",
        json={
            "specials": {"items": [game(10)]},
            "top_sellers": {"items": [game(10), game(20, 2999)]},
            "new_releases": {"items": []},
        },
    )
    source = SteamStoreSource(
        organization_id="org", source_id="steam", base_url="https://store.example/"
    )
    result = source.collect()
    assert len(result.products) == 2
    assert result.products[0].price == Decimal("41.99")
    assert result.products[0].old_price == Decimal("59.99")
    assert result.products[0].availability is Availability.IN_STOCK
    assert result.products[0].attributes["linux"] == "True"
    assert result.stats.records_found == 3
    assert result.stats.complete_snapshot is True


def test_zero_page_limit_returns_no_request() -> None:
    source = SteamStoreSource(organization_id="org", source_id="steam")
    result = source.collect(max_pages=0)
    assert result.products == []
    assert result.stats.complete_snapshot is False
