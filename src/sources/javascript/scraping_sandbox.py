"""Playwright adapter for a legal infinite-scroll product playground."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.normalization import normalize_product
from src.sources.base import ProductSource, SourceRunResult, SourceRunStats

LOGGER = logging.getLogger(__name__)


class ScrapingSandboxSource(ProductSource):
    def __init__(
        self,
        *,
        organization_id: str,
        source_id: str,
        base_url: str = "https://scrapingsandbox.com/infinite-scroll",
        default_currency: str = "USD",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        scroll_wait_ms: int = 3000,
        headless: bool = True,
    ) -> None:
        self.organization_id = organization_id
        self.source_id = source_id
        self.base_url = base_url
        self.default_currency = default_currency
        self.timeout_ms = int(timeout_seconds * 1000)
        self.max_retries = max_retries
        self.scroll_wait_ms = scroll_wait_ms
        self.headless = headless

    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        html, batches, complete = self._render(max_pages)
        return self._parse_html(html, batches=batches, complete=complete)

    def _render(self, max_pages: int | None) -> tuple[str, int, bool]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=self.headless)
                    try:
                        page = browser.new_page()
                        page.goto(
                            self.base_url,
                            wait_until="networkidle",
                            timeout=self.timeout_ms,
                        )
                        page.locator(".product-card").first.wait_for(
                            state="visible", timeout=self.timeout_ms
                        )
                        batches = 1
                        complete = False
                        while max_pages is None or batches < max_pages:
                            previous_count = page.locator(".product-card").count()
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            try:
                                page.wait_for_function(
                                    "count => document.querySelectorAll('.product-card').length > count",
                                    arg=previous_count,
                                    timeout=self.scroll_wait_ms,
                                )
                            except PlaywrightTimeoutError:
                                complete = True
                                break
                            batches += 1
                        return page.content(), batches, complete
                    finally:
                        browser.close()
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Browser attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
        assert last_error is not None
        raise last_error

    def _parse_html(
        self, html: str, *, batches: int, complete: bool
    ) -> SourceRunResult:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".product-card")
        stats = SourceRunStats(
            pages_fetched=batches,
            records_found=len(cards),
            complete_snapshot=complete,
        )
        products = []
        collected_at = datetime.now(timezone.utc)
        for card in cards:
            try:
                href = card.get("href")
                sku_node = card.select_one(".sku")
                name_node = card.select_one(".product-name")
                price_node = card.select_one(".price")
                if not href or not sku_node or not name_node or not price_node:
                    raise ValueError("required card fields are missing")
                url = urljoin(self.base_url, str(href))
                external_id = urlsplit(url).path.rstrip("/").split("/")[-1]
                image = card.select_one("img.product-image")
                old_price = card.select_one(".compare-at-price")
                products.append(
                    normalize_product(
                        organization_id=self.organization_id,
                        source_id=self.source_id,
                        external_id=external_id,
                        sku=sku_node.get_text(" ", strip=True),
                        name=name_node.get_text(" ", strip=True),
                        brand=self._text(card, ".vendor"),
                        category=self._text(card, ".category"),
                        description=None,
                        price=price_node.get_text(" ", strip=True),
                        old_price=old_price.get_text(" ", strip=True) if old_price else None,
                        currency=self.default_currency,
                        availability=self._text(card, ".availability"),
                        quantity=None,
                        rating=self._text(card, ".rating"),
                        review_count=None,
                        url=url,
                        image_url=image.get("src") if image else None,
                        attributes=None,
                        collected_at=collected_at,
                    )
                )
                stats.records_processed += 1
            except (TypeError, ValueError) as exc:
                stats.records_skipped += 1
                stats.errors.append(str(exc))
                LOGGER.warning("Skipping rendered product: %s", exc)
        return SourceRunResult(
            self.organization_id, self.source_id, products, stats
        )

    @staticmethod
    def _text(card, selector: str) -> str | None:
        node = card.select_one(selector)
        return node.get_text(" ", strip=True) if node else None
