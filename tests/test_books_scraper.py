from pathlib import Path

import requests
import responses

from src.models import Availability
from src.sources.html.books_demo import BooksDemoSource

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@responses.activate
def test_scrapes_pagination_and_skips_bad_card() -> None:
    responses.get("https://example.test/", body=fixture("catalogue_page_1.html"))
    responses.get(
        "https://example.test/catalogue/alpha_1/index.html",
        body=fixture("product.html"),
    )
    responses.get(
        "https://example.test/catalogue/page-2.html",
        body=fixture("catalogue_page_2.html"),
    )
    responses.get(
        "https://example.test/catalogue/beta_2/index.html",
        body=fixture("product.html").replace("abc-123", "def-456"),
    )

    source = BooksDemoSource(base_url="https://example.test/")
    result = source.collect()
    products = result.products

    assert [item.product_id for item in products] == ["abc-123", "def-456"]
    assert products[0].name == "Alpha & Omega"
    assert products[0].category == "Test Category"
    assert str(products[0].price) == "12.34"
    assert products[0].currency == "GBP"
    assert products[0].availability is Availability.IN_STOCK
    assert products[0].rating == 4
    assert products[0].organization_id == "demo"
    assert products[0].source_id == "books-demo"
    assert products[0].collected_at.isoformat().endswith("+00:00")
    assert result.stats.pages_fetched == 2
    assert result.stats.records_found == 3
    assert result.stats.records_processed == 2
    assert result.stats.records_skipped == 1
    assert len(result.stats.errors) == 1


@responses.activate
def test_max_pages_stops_pagination() -> None:
    responses.get("https://example.test/", body=fixture("catalogue_page_1.html"))
    responses.get(
        "https://example.test/catalogue/alpha_1/index.html",
        body=fixture("product.html"),
    )

    products = BooksDemoSource(base_url="https://example.test/").collect(
        max_pages=1
    ).products

    assert len(products) == 1


@responses.activate
def test_retries_transient_catalogue_error() -> None:
    responses.get("https://example.test/", status=503)
    responses.get("https://example.test/", body=fixture("catalogue_page_2.html"))
    responses.get(
        "https://example.test/beta_2/index.html",
        body=fixture("product.html"),
    )

    result = BooksDemoSource(
        base_url="https://example.test/", backoff_factor=0
    ).collect()

    assert len(result.products) == 1
    catalogue_calls = [call for call in responses.calls if call.request.url == "https://example.test/"]
    assert len(catalogue_calls) == 2


@responses.activate
def test_network_failure_for_one_product_does_not_stop_others() -> None:
    catalogue = """
    <article class="product_pod"><h3><a href="bad/index.html">Bad</a></h3></article>
    <article class="product_pod"><h3><a href="good/index.html">Good</a></h3></article>
    """
    responses.get("https://example.test/", body=catalogue)
    responses.get(
        "https://example.test/bad/index.html",
        body=requests.ConnectionError("connection lost"),
    )
    responses.get(
        "https://example.test/good/index.html",
        body=fixture("product.html"),
    )

    result = BooksDemoSource(
        base_url="https://example.test/", max_retries=0
    ).collect()

    assert len(result.products) == 1
    assert result.stats.records_found == 2
    assert result.stats.records_processed == 1
    assert result.stats.records_skipped == 1
    assert "connection lost" in result.stats.errors[0]
    assert result.stats.complete_snapshot is True
