"""Configurable CSV/XML supplier catalogue adapter."""

from __future__ import annotations

import csv
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.normalization import normalize_product
from src.sources.base import ProductSource, SourceRunResult, SourceRunStats

LOGGER = logging.getLogger(__name__)


class CatalogFileSource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        path: str | Path,
        default_currency: str | None = None,
        file_format: str | None = None,
        delimiter: str = ",",
        record_path: str = ".//product",
        field_mapping: dict[str, str] | None = None,
        attribute_fields: list[str] | None = None,
        page_size: int = 1000,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.path = Path(path)
        self.default_currency = default_currency
        self.file_format = (file_format or self.path.suffix.lstrip(".")).casefold()
        self.delimiter = delimiter
        self.record_path = record_path
        self.field_mapping = field_mapping or {}
        self.attribute_fields = attribute_fields or []
        self.page_size = page_size
        if self.file_format not in {"csv", "xml"}:
            raise ValueError(f"unsupported catalogue file format: {self.file_format!r}")
        if page_size <= 0:
            raise ValueError("file page_size must be positive")

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        rows = list(self._read_rows())
        limit = len(rows) if max_pages is None else min(len(rows), max_pages * self.page_size)
        stats = SourceRunStats(records_found=limit)
        products = []
        collected_at = datetime.now(timezone.utc)
        for raw in rows[:limit]:
            try:
                products.append(self._normalize(raw, collected_at))
                stats.records_processed += 1
            except (KeyError, TypeError, ValueError) as exc:
                stats.records_skipped += 1
                stats.errors.append(str(exc))
                LOGGER.warning("Skipping supplier file product: %s", exc)
        stats.pages_fetched = (limit + self.page_size - 1) // self.page_size if limit else 1
        stats.complete_snapshot = limit == len(rows)
        return SourceRunResult(self.organization_id, self.source_id, products, stats)

    def _read_rows(self) -> Iterable[dict[str, Any]]:
        if self.file_format == "csv":
            with self.path.open(encoding="utf-8-sig", newline="") as stream:
                yield from csv.DictReader(stream, delimiter=self.delimiter)
            return
        root = ET.parse(self.path).getroot()
        for node in root.findall(self.record_path):
            yield {child.tag: child.text for child in node}

    def _value(self, raw: dict[str, Any], canonical: str, default: Any = None) -> Any:
        return raw.get(self.field_mapping.get(canonical, canonical), default)

    def _normalize(self, raw: dict[str, Any], collected_at: datetime):
        attributes = {
            field: raw.get(self.field_mapping.get(field, field))
            for field in self.attribute_fields
        }
        return normalize_product(
            organization_id=self.organization_id,
            source_id=self.source_id,
            external_id=self._value(raw, "external_id"),
            sku=self._value(raw, "sku"),
            name=self._value(raw, "name"),
            brand=self._value(raw, "brand"),
            category=self._value(raw, "category"),
            description=self._value(raw, "description"),
            price=self._value(raw, "price"),
            old_price=self._value(raw, "old_price"),
            currency=self._value(raw, "currency", self.default_currency),
            availability=self._value(raw, "availability"),
            quantity=self._value(raw, "quantity"),
            rating=self._value(raw, "rating"),
            review_count=self._value(raw, "review_count"),
            url=self._value(raw, "url"),
            image_url=self._value(raw, "image_url"),
            attributes=attributes,
            collected_at=collected_at,
        )
