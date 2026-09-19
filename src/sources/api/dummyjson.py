"""REST API adapter for the DummyJSON product catalogue."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

import requests

from src.normalization import normalize_product
from src.scraper.base import create_retrying_session
from src.sources.base import ProductSource, SourceRunResult, SourceRunStats

LOGGER = logging.getLogger(__name__)


class DummyJsonSource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        base_url: str = "https://dummyjson.com/",
        default_currency: str = "USD",
        page_size: int = 30,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        session: requests.Session | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url.rstrip("/") + "/"
        self.default_currency = default_currency
        self.page_size = page_size
        self.timeout_seconds = timeout_seconds
        self.session = session or create_retrying_session(max_retries, backoff_factor)

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        products = []
        stats = SourceRunStats()
        skip = 0
        total: int | None = None

        while total is None or skip < total:
            if max_pages is not None and stats.pages_fetched >= max_pages:
                break
            response = self.session.get(
                urljoin(self.base_url, "products"),
                params={"limit": self.page_size, "skip": skip},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            raw_products = payload.get("products")
            if not isinstance(raw_products, list):
                raise ValueError("API response does not contain a products list")
            total = int(payload.get("total", len(raw_products)))
            stats.pages_fetched += 1
            stats.records_found += len(raw_products)
            collected_at = datetime.now(timezone.utc)

            for raw in raw_products:
                try:
                    products.append(self._normalize(raw, collected_at))
                    stats.records_processed += 1
                except (KeyError, TypeError, ValueError) as exc:
                    stats.records_skipped += 1
                    identifier = raw.get("id") if isinstance(raw, dict) else None
                    message = f"product {identifier!r}: {exc}"
                    stats.errors.append(message)
                    LOGGER.warning("Skipping API product: %s", message)

            skip += len(raw_products)
            if not raw_products:
                break

        stats.complete_snapshot = total is not None and skip >= total
        return SourceRunResult(
            self.organization_id, self.source_id, products, stats
        )

    def _normalize(self, raw: dict[str, Any], collected_at: datetime):
        price = Decimal(str(raw["price"]))
        discount = Decimal(str(raw.get("discountPercentage") or 0))
        old_price = None
        if 0 < discount < 100:
            old_price = price / (Decimal("1") - discount / Decimal("100"))
        reviews = raw.get("reviews") or []
        meta = raw.get("meta") or {}
        dimensions = raw.get("dimensions") or {}
        attributes = {
            "gtin": meta.get("barcode"),
            "weight": raw.get("weight"),
            "width": dimensions.get("width"),
            "height": dimensions.get("height"),
            "depth": dimensions.get("depth"),
        }
        return normalize_product(
            organization_id=self.organization_id,
            source_id=self.source_id,
            external_id=raw["id"],
            sku=raw.get("sku"),
            name=raw["title"],
            brand=raw.get("brand"),
            category=raw.get("category"),
            description=raw.get("description"),
            price=price,
            old_price=old_price,
            currency=self.default_currency,
            availability=raw.get("availabilityStatus") or (raw.get("stock", 0) > 0),
            quantity=raw.get("stock"),
            rating=raw.get("rating"),
            review_count=len(reviews),
            url=urljoin(self.base_url, f"products/{raw['id']}"),
            image_url=raw.get("thumbnail"),
            attributes=attributes,
            collected_at=collected_at,
        )

