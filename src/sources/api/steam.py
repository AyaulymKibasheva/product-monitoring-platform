"""Public Steam Store adapter for live regional prices and discounts."""

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
from src.sources.rate_limit import RequestPacer

LOGGER = logging.getLogger(__name__)


class SteamStoreSource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        base_url: str = "https://store.steampowered.com/",
        country_code: str = "us",
        language: str = "en",
        sections: tuple[str, ...] = ("specials", "top_sellers", "new_releases"),
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        session: requests.Session | None = None,
        delay_seconds: float = 0.25,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url.rstrip("/") + "/"
        self.country_code = country_code.casefold()
        self.language = language.casefold()
        self.sections = sections
        self.timeout_seconds = timeout_seconds
        self.session = session or create_retrying_session(max_retries, backoff_factor)
        self.pacer = RequestPacer(delay_seconds)

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        stats = SourceRunStats()
        if max_pages == 0:
            return SourceRunResult(self.organization_id, self.source_id, [], stats)
        self.pacer.wait()
        response = self.session.get(
            urljoin(self.base_url, "api/featuredcategories"),
            params={"cc": self.country_code, "l": self.language},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        stats.pages_fetched = 1
        collected_at = datetime.now(timezone.utc)
        products = []
        seen: set[str] = set()
        for section in self.sections:
            group = payload.get(section) or {}
            raw_products = group.get("items") if isinstance(group, dict) else None
            if not isinstance(raw_products, list):
                continue
            for raw in raw_products:
                stats.records_found += 1
                identifier = str(raw.get("id")) if isinstance(raw, dict) else ""
                if identifier in seen:
                    continue
                seen.add(identifier)
                try:
                    products.append(self._normalize(raw, section, collected_at))
                    stats.records_processed += 1
                except (KeyError, TypeError, ValueError) as exc:
                    stats.records_skipped += 1
                    message = f"product {identifier!r}: {exc}"
                    stats.errors.append(message)
                    LOGGER.warning("Skipping Steam product: %s", message)
        stats.complete_snapshot = True
        return SourceRunResult(self.organization_id, self.source_id, products, stats)

    def _normalize(self, raw: dict[str, Any], section: str, collected_at: datetime):
        current_price = Decimal(str(raw["final_price"])) / Decimal("100")
        original_price = Decimal(str(raw.get("original_price") or raw["final_price"])) / Decimal("100")
        old_price = original_price if original_price != current_price else None
        app_id = str(raw["id"])
        return normalize_product(
            organization_id=self.organization_id,
            source_id=self.source_id,
            external_id=app_id,
            sku=f"STEAM-{app_id}",
            name=raw["name"],
            brand="Steam",
            category=section.replace("_", " "),
            price=current_price,
            old_price=old_price,
            currency=raw.get("currency") or "USD",
            availability=True,
            rating=None,
            url=f"https://store.steampowered.com/app/{app_id}/",
            image_url=raw.get("large_capsule_image") or raw.get("header_image"),
            attributes={
                "discount_percent": raw.get("discount_percent"),
                "windows": raw.get("windows_available"),
                "mac": raw.get("mac_available"),
                "linux": raw.get("linux_available"),
                "controller_support": raw.get("controller_support"),
            },
            collected_at=collected_at,
        )
