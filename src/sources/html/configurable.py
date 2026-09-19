"""Configurable static HTML product source driven by CSS selectors."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from src.normalization import normalize_product
from src.scraper.base import create_retrying_session
from src.sources.base import ProductSource, SourceRunResult, SourceRunStats
from src.sources.rate_limit import RequestPacer

LOGGER = logging.getLogger(__name__)


class ConfigurableHtmlSource(ProductSource):
    """Collect product cards from one or more server-rendered HTML pages."""

    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        base_url: str,
        page_urls: list[str],
        selectors: dict[str, str],
        default_currency: str | None = None,
        timeout_seconds: float = 10,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        delay_seconds: float = 0,
        session: requests.Session | None = None,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url
        self.page_urls = page_urls or [base_url]
        self.selectors = selectors
        self.default_currency = default_currency
        self.timeout_seconds = timeout_seconds
        self.session = session or create_retrying_session(max_retries, backoff_factor)
        self.pacer = RequestPacer(delay_seconds)
        for field in ("item", "name", "price", "url"):
            if not selectors.get(field):
                raise ValueError(f"selector {field!r} is required")

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        products = []
        stats = SourceRunStats()
        urls = self.page_urls[:max_pages] if max_pages else self.page_urls
        for page_url in urls:
            try:
                self.pacer.wait()
                response = self.session.get(page_url, timeout=self.timeout_seconds)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, "html.parser")
            except requests.RequestException as exc:
                stats.errors.append(f"{page_url}: {exc}")
                continue
            stats.pages_fetched += 1
            cards = soup.select(self.selectors["item"])
            stats.records_found += len(cards)
            for card in cards:
                try:
                    product_url = self._attribute(card, "url", "href", required=True)
                    absolute_url = urljoin(page_url, product_url)
                    external_id = self._value(card, "external_id") or hashlib.sha256(
                        absolute_url.encode("utf-8")
                    ).hexdigest()[:24]
                    products.append(
                        normalize_product(
                            organization_id=self.organization_id,
                            source_id=self.source_id,
                            external_id=external_id,
                            sku=self._value(card, "sku"),
                            name=self._value(card, "name", required=True),
                            category=self._value(card, "category"),
                            brand=self._value(card, "brand"),
                            price=self._value(card, "price", required=True),
                            currency=self.default_currency,
                            availability=self._value(card, "availability"),
                            rating=self._value(card, "rating"),
                            url=absolute_url,
                            image_url=self._attribute(card, "image", "src"),
                            collected_at=datetime.now(timezone.utc),
                            base_url=page_url,
                        )
                    )
                    stats.records_processed += 1
                except (TypeError, ValueError, KeyError) as exc:
                    stats.records_skipped += 1
                    stats.errors.append(f"{page_url}: {exc}")
                    LOGGER.warning("Skipping configurable HTML product: %s", exc)
        stats.complete_snapshot = len(stats.errors) == 0
        return SourceRunResult(self.organization_id, self.source_id, products, stats)

    def _node(self, card: Tag, field: str) -> Tag | None:
        selector = self.selectors.get(field)
        return card.select_one(selector) if selector else None

    def _value(self, card: Tag, field: str, *, required: bool = False) -> str | None:
        node = self._node(card, field)
        value = node.get_text(" ", strip=True) if node else None
        if required and not value:
            raise ValueError(f"required field {field!r} was not found")
        return value

    def _attribute(
        self, card: Tag, field: str, attribute: str, *, required: bool = False
    ) -> str | None:
        node = self._node(card, field)
        value = str(node.get(attribute, "")).strip() if node else None
        if required and not value:
            raise ValueError(f"required attribute {field!r}.{attribute} was not found")
        return value or None
