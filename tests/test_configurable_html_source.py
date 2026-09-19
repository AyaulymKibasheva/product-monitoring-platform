from decimal import Decimal

import responses

from src.sources.html.configurable import ConfigurableHtmlSource


HTML = """
<div class="product"><a class="link" href="/p/1"><span class="name">Coffee maker</span></a>
<span class="price">$49.90</span><span class="stock">In stock</span><span class="rating">4.5</span></div>
<div class="product"><a class="link" href="/p/2"><span class="name">Kettle</span></a>
<span class="price">$20</span><span class="stock">Out of stock</span></div>
"""


@responses.activate
def test_collects_products_using_css_configuration() -> None:
    responses.get("https://shop.test/catalog", body=HTML)
    source = ConfigurableHtmlSource(
        organization_id="org",
        source_id="shop",
        base_url="https://shop.test/catalog",
        page_urls=["https://shop.test/catalog"],
        default_currency="USD",
        selectors={
            "item": ".product",
            "name": ".name",
            "price": ".price",
            "url": ".link",
            "availability": ".stock",
            "rating": ".rating",
        },
    )
    result = source.collect()
    assert result.stats.complete_snapshot is True
    assert len(result.products) == 2
    assert result.products[0].price == Decimal("49.90")
    assert result.products[0].rating == 4.5
    assert result.products[0].url == "https://shop.test/p/1"
    assert result.products[0].external_id != result.products[1].external_id


def test_requires_core_selectors() -> None:
    try:
        ConfigurableHtmlSource(
            organization_id="org", source_id="shop", base_url="https://shop.test",
            page_urls=[], selectors={"item": ".product"},
        )
    except ValueError as exc:
        assert "selector" in str(exc)
    else:
        raise AssertionError("missing selectors must fail")
