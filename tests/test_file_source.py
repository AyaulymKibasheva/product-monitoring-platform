from decimal import Decimal

from src.sources.file import CatalogFileSource


def test_csv_supplier_file_maps_fields_and_skips_bad_rows() -> None:
    source = CatalogFileSource(
        organization_id="org",
        source_id="supplier",
        path="tests/fixtures/supplier_products.csv",
        field_mapping={
            "external_id": "id", "sku": "article", "name": "title",
            "brand": "maker", "category": "group", "price": "cost",
            "availability": "state", "quantity": "stock", "url": "link",
        },
        attribute_fields=["mass"],
    )

    result = source.collect()

    assert result.stats.records_found == 2
    assert result.stats.records_processed == 1
    assert result.stats.records_skipped == 1
    assert result.stats.complete_snapshot is True
    assert result.products[0].price == Decimal("1299.99")
    assert result.products[0].attributes == {"mass": "1000 g"}


def test_xml_supplier_file_is_supported() -> None:
    source = CatalogFileSource(
        organization_id="org",
        source_id="xml",
        path="tests/fixtures/supplier_products.xml",
        file_format="xml",
        field_mapping={"external_id": "id"},
    )

    result = source.collect(max_pages=1)

    assert len(result.products) == 1
    assert result.products[0].currency == "EUR"
    assert result.stats.complete_snapshot is True
