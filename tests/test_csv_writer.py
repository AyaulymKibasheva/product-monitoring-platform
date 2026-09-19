import csv
from datetime import datetime, timezone
from decimal import Decimal

from src.models import Availability, Product
from src.utils.csv_writer import write_products_csv


def test_writes_utf8_csv_with_stable_columns(tmp_path) -> None:
    destination = tmp_path / "nested" / "products.csv"
    product = Product(
        organization_id="org-1",
        source_id="source-1",
        external_id="id-1",
        name="Test",
        category=None,
        price=Decimal("12.30"),
        currency="USD",
        availability=Availability.IN_STOCK,
        url="https://example.test/item",
        collected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        rating=4.5,
        attributes={"color": "blue"},
    )

    write_products_csv([product], destination)

    with destination.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["organization_id"] == "org-1"
    assert rows[0]["source_id"] == "source-1"
    assert rows[0]["external_id"] == "id-1"
    assert rows[0]["price"] == "12.30"
    assert rows[0]["availability"] == "in_stock"
    assert rows[0]["attributes"] == '{"color": "blue"}'
    assert rows[0]["collected_at"] == "2026-01-01T00:00:00+00:00"
    assert destination.exists()
