"""Source adapters and registry."""

from .base import ProductSource, SourceRunResult, SourceRunStats
from .catalog import SourceCatalog, load_source_catalog
from .registry import SourceRegistry, build_default_registry, build_registry

__all__ = [
    "ProductSource",
    "SourceCatalog",
    "SourceRegistry",
    "SourceRunResult",
    "SourceRunStats",
    "build_default_registry",
    "build_registry",
    "load_source_catalog",
]
