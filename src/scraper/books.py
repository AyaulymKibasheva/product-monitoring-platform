"""Deprecated compatibility import for the original demonstration scraper."""

from src.sources.html.books_demo import BooksDemoSource


class BooksToScrapeScraper(BooksDemoSource):
    """Compatibility wrapper; new code should use BooksDemoSource.collect()."""

    def scrape(self, max_pages: int | None = None):
        return self.collect(max_pages=max_pages).products
