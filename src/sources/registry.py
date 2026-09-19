"""Registry used to select adapters without coupling the application to them."""

from __future__ import annotations

from collections.abc import Iterable

from src.models import SourceDefinition

from .base import ProductSource
from .catalog import SourceCatalog, load_source_catalog


class SourceRegistry:
    def __init__(self, sources: Iterable[ProductSource] = ()) -> None:
        self._sources: dict[str, ProductSource] = {}
        for source in sources:
            self.register(source)

    def register(self, source: ProductSource) -> None:
        if source.source_id in self._sources:
            raise ValueError(f"duplicate source ID: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> ProductSource:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            available = ", ".join(self.ids()) or "none"
            raise ValueError(
                f"unknown source {source_id!r}; available sources: {available}"
            ) from exc

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._sources))


def build_registry(catalog: SourceCatalog) -> SourceRegistry:
    """Instantiate active sources through a small explicit adapter factory."""
    from .html.books_demo import BooksDemoSource
    from .api.dummyjson import DummyJsonSource
    from .javascript.scraping_sandbox import ScrapingSandboxSource

    factories = {
        "books_demo": lambda definition: BooksDemoSource(
            organization_id=definition.organization_id,
            source_id=definition.source_id,
            base_url=_required_url(definition),
            timeout_seconds=definition.timeout_seconds,
            max_retries=definition.max_retries,
            backoff_factor=definition.backoff_factor,
        ),
        "dummyjson": lambda definition: DummyJsonSource(
            organization_id=definition.organization_id,
            source_id=definition.source_id,
            base_url=_required_url(definition),
            default_currency=definition.default_currency or "USD",
            page_size=int(definition.settings.get("page_size", 30)),
            timeout_seconds=definition.timeout_seconds,
            max_retries=definition.max_retries,
            backoff_factor=definition.backoff_factor,
        ),
        "scraping_sandbox": lambda definition: ScrapingSandboxSource(
            organization_id=definition.organization_id,
            source_id=definition.source_id,
            base_url=_required_url(definition),
            default_currency=definition.default_currency or "USD",
            timeout_seconds=definition.timeout_seconds,
            max_retries=definition.max_retries,
            scroll_wait_ms=int(definition.settings.get("scroll_wait_ms", 3000)),
            headless=bool(definition.settings.get("headless", True)),
        ),
    }
    adapters: list[ProductSource] = []
    active_organizations = {
        item.organization_id for item in catalog.organizations if item.active
    }
    for definition in catalog.sources:
        if not definition.active or definition.organization_id not in active_organizations:
            continue
        try:
            factory = factories[definition.adapter]
        except KeyError as exc:
            raise ValueError(
                f"unknown adapter {definition.adapter!r} for source {definition.source_id!r}"
            ) from exc
        adapters.append(factory(definition))
    return SourceRegistry(adapters)


def build_default_registry(settings) -> SourceRegistry:
    return build_registry(load_source_catalog(settings.source_config_path))


def _required_url(definition: SourceDefinition) -> str:
    if not definition.base_url:
        raise ValueError(f"source {definition.source_id!r} requires base_url")
    return definition.base_url
