import csv
import io
import zipfile

from src.reports import products_csv, products_xlsx


def test_csv_and_xlsx_downloads_are_valid() -> None:
    rows = [{"name": "Товар", "price": 12.5, "currency": "KZT", "url": "https://x.test/p"}]
    decoded = products_csv(rows).decode("utf-8-sig")
    assert list(csv.DictReader(io.StringIO(decoded)))[0]["name"] == "Товар"
    payload = products_xlsx(rows)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        assert "Товар" in archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
