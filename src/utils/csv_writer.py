"""CSV snapshot output."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from src.models import Product

CSV_FIELDS = (
    "organization_id",
    "source_id",
    "external_id",
    "sku",
    "name",
    "brand",
    "category",
    "description",
    "price",
    "old_price",
    "currency",
    "availability",
    "quantity",
    "rating",
    "review_count",
    "url",
    "image_url",
    "attributes",
    "collected_at",
)


def write_products_csv(products: Iterable[Product], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            row = asdict(product)
            row["price"] = str(product.price)
            row["old_price"] = str(product.old_price) if product.old_price is not None else ""
            row["availability"] = product.availability.value
            row["attributes"] = (
                json.dumps(product.attributes, ensure_ascii=False, sort_keys=True)
                if product.attributes
                else ""
            )
            row["collected_at"] = product.collected_at.isoformat()
            writer.writerow(row)
