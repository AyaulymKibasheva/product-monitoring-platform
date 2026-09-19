"""Demonstration static-HTML adapter for books.toscrape.com."""

from __future__ import annotations

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
RATING_VALUES = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


class BooksDemoSource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str = "demo",
        source_id: str = "books-demo",
        base_url: str = "https://books.toscrape.com/",
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        session: requests.Session | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.session = session or create_retrying_session(max_retries, backoff_factor)
        self.pacer = RequestPacer(delay_seconds)

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        products = []
        stats = SourceRunStats()
        page_url: str | None = self.base_url

        while page_url and (max_pages is None or stats.pages_fetched < max_pages):
            stats.pages_fetched += 1
            LOGGER.info("Fetching page %d: %s", stats.pages_fetched, page_url)
            soup = self._fetch_soup(page_url)
            collected_at = datetime.now(timezone.utc)
            cards = soup.select("article.product_pod")
            stats.records_found += len(cards)

            for card in cards:
                try:
                    product = self._parse_detail(
                        self._detail_url(card, page_url), collected_at
                    )
                except (KeyError, ValueError, TypeError, requests.RequestException) as exc:
                    message = f"{page_url}: {exc}"
                    stats.records_skipped += 1
                    stats.errors.append(message)
                    LOGGER.warning("Skipping product: %s", message)
                    continue
                products.append(product)
                stats.records_processed += 1

            next_link = soup.select_one("li.next a")
            page_url = urljoin(page_url, str(next_link.get("href"))) if next_link else None

        stats.complete_snapshot = page_url is None

        return SourceRunResult(
            organization_id=self.organization_id,
            source_id=self.source_id,
            products=products,
            stats=stats,
        )

    def _fetch_soup(self, url: str) -> BeautifulSoup:
        self.pacer.wait()
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")

    @staticmethod
    def _detail_url(card: Tag, page_url: str) -> str:
        link = card.select_one("h3 a")
        href = link.get("href") if link else None
        if not href:
            raise ValueError("product URL is missing")
        return urljoin(page_url, str(href))

    def _parse_detail(self, url: str, collected_at: datetime):
        soup = self._fetch_soup(url)
        title_node = soup.select_one("div.product_main h1")
        price_node = soup.select_one("div.product_main p.price_color")
        availability_node = soup.select_one("div.product_main p.availability")
        rating_node = soup.select_one("div.product_main p.star-rating")
        image_node = soup.select_one("div.item.active img")
        description_node = soup.select_one("#product_description + p")

        table = {
            row.th.get_text(strip=True): row.td.get_text(strip=True)
            for row in soup.select("table.table.table-striped tr")
            if row.th and row.td
        }
        external_id = table.get("UPC")
        if not external_id or not title_node or not price_node:
            raise ValueError("required product fields are missing")

        breadcrumbs = soup.select("ul.breadcrumb li a")
        category = breadcrumbs[-1].get_text(" ", strip=True) if breadcrumbs else None
        rating = None
        if rating_node:
            rating = next(
                (value for name, value in RATING_VALUES.items() if name in rating_node.get("class", [])),
                None,
            )

        return normalize_product(
            organization_id=self.organization_id,
            source_id=self.source_id,
            external_id=external_id,
            sku=external_id,
            name=title_node.get_text(" ", strip=True),
            category=category,
            brand=None,
            description=description_node.get_text(" ", strip=True) if description_node else None,
            price=price_node.get_text(strip=True),
            old_price=None,
            currency=None,
            availability=availability_node.get_text(" ", strip=True) if availability_node else None,
            quantity=None,
            rating=rating,
            review_count=table.get("Number of reviews"),
            url=url,
            image_url=image_node.get("src") if image_node else None,
            attributes={"product_type": table.get("Product Type", "")},
            collected_at=collected_at,
            base_url=url,
        )
