"""Best Buy Products API adapter with near-real-time retail pricing."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

import requests

from src.normalization import normalize_product
from src.scraper.base import create_retrying_session
from src.sources.base import ProductSource, SourceRunResult, SourceRunStats
from src.sources.rate_limit import RequestPacer

LOGGER = logging.getLogger(__name__)


class BestBuySource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        base_url: str = "https://api.bestbuy.com/v1/",
        api_key_env: str = "BESTBUY_API_KEY",
        page_size: int = 50,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        session: requests.Session | None = None,
        delay_seconds: float = 0.25,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key_env = api_key_env
        self.page_size = min(max(page_size, 1), 100)
        self.timeout_seconds = timeout_seconds
        self.session = session or create_retrying_session(max_retries, backoff_factor)
        self.pacer = RequestPacer(delay_seconds)

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Best Buy API key is missing; set {self.api_key_env} in the environment"
            )
        products = []
        stats = SourceRunStats()
        page = 1
        total_pages: int | None = None
        fields = (
            "sku,name,manufacturer,categoryPath,salePrice,regularPrice,onSale,"
            "onlineAvailability,url,image,customerReviewAverage,customerReviewCount,"
            "shortDescription,upc,modelNumber,color"
        )
        while total_pages is None or page <= total_pages:
            if max_pages is not None and stats.pages_fetched >= max_pages:
                break
            self.pacer.wait()
            params: dict[str, str | int] = {
                "apiKey": api_key,
                "format": "json",
                "page": page,
                "pageSize": self.page_size,
                "show": fields,
            }
            response = self.session.get(
                urljoin(self.base_url, "products((onlineAvailability=true))"),
                params=params,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            raw_products = payload.get("products")
            if not isinstance(raw_products, list):
                raise ValueError("Best Buy response does not contain a products list")
            total_pages = int(payload.get("totalPages", page))
            stats.pages_fetched += 1
            stats.records_found += len(raw_products)
            collected_at = datetime.now(timezone.utc)
            for raw in raw_products:
                try:
                    products.append(self._normalize(raw, collected_at))
                    stats.records_processed += 1
                except (KeyError, TypeError, ValueError) as exc:
                    stats.records_skipped += 1
                    identifier = raw.get("sku") if isinstance(raw, dict) else None
                    message = f"product {identifier!r}: {exc}"
                    stats.errors.append(message)
                    LOGGER.warning("Skipping Best Buy product: %s", message)
            page += 1
            if not raw_products:
                break
        stats.complete_snapshot = total_pages is not None and page > total_pages
        return SourceRunResult(self.organization_id, self.source_id, products, stats)

    def _normalize(self, raw: dict[str, Any], collected_at: datetime):
        category_path = raw.get("categoryPath") or []
        category = next(
            (
                item.get("name")
                for item in reversed(category_path)
                if isinstance(item, dict) and item.get("name")
            ),
            None,
        )
        sale_price = Decimal(str(raw["salePrice"]))
        regular_price = raw.get("regularPrice")
        old_price = None
        if regular_price is not None and Decimal(str(regular_price)) != sale_price:
            old_price = Decimal(str(regular_price))
        return normalize_product(
            organization_id=self.organization_id,
            source_id=self.source_id,
            external_id=raw["sku"],
            sku=raw.get("modelNumber") or str(raw["sku"]),
            name=raw["name"],
            brand=raw.get("manufacturer"),
            category=category,
            description=raw.get("shortDescription"),
            price=sale_price,
            old_price=old_price,
            currency="USD",
            availability=bool(raw.get("onlineAvailability")),
            rating=raw.get("customerReviewAverage"),
            review_count=raw.get("customerReviewCount"),
            url=raw["url"],
            image_url=raw.get("image"),
            attributes={
                "upc": raw.get("upc"),
                "model": raw.get("modelNumber"),
                "color": raw.get("color"),
                "on_sale": str(bool(raw.get("onSale"))).lower(),
            },
            collected_at=collected_at,
        )
