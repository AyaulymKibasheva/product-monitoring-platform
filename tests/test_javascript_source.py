from decimal import Decimal

from src.models import Availability
from src.sources.javascript.scraping_sandbox import ScrapingSandboxSource

RENDERED_HTML = """
<html><body>
  <a class="product-card" href="/product/42">
    <img class="product-image" src="https://cdn.example/42.png" />
    <span class="vendor">Acme</span>
    <span class="rating">4.6</span>
    <h3 class="product-name">Dynamic Product</h3>
    <span class="price">$80.00</span>
    <span class="compare-at-price">$100.00</span>
    <span class="category">Electronics</span>
    <span class="sku">SKU-42</span>
    <span class="availability">In Stock</span>
  </a>
  <a class="product-card" href="/product/broken">
    <h3 class="product-name">Broken</h3>
  </a>
</body></html>
"""


def test_parses_browser_rendered_products_and_skips_bad_card() -> None:
    source = ScrapingSandboxSource(
        organization_id="org",
        source_id="js",
        base_url="https://sandbox.example/infinite-scroll",
    )

    result = source._parse_html(RENDERED_HTML, batches=2, complete=True)

    assert len(result.products) == 1
    product = result.products[0]
    assert product.external_id == "42"
    assert product.sku == "SKU-42"
    assert product.brand == "Acme"
    assert product.price == Decimal("80.00")
    assert product.old_price == Decimal("100.00")
    assert product.availability is Availability.IN_STOCK
    assert product.url == "https://sandbox.example/product/42"
    assert result.stats.pages_fetched == 2
    assert result.stats.records_found == 2
    assert result.stats.records_skipped == 1
    assert result.stats.complete_snapshot is True


def test_collect_uses_rendered_document(monkeypatch) -> None:
    source = ScrapingSandboxSource(
        organization_id="org",
        source_id="js",
        base_url="https://sandbox.example/infinite-scroll",
    )
    monkeypatch.setattr(
        source,
        "_render",
        lambda max_pages: (RENDERED_HTML, max_pages or 2, max_pages is None),
    )

    result = source.collect(max_pages=1)

    assert len(result.products) == 1
    assert result.stats.pages_fetched == 1
    assert result.stats.complete_snapshot is False
