"""Universal contract implemented by every product source adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.models import Product


@dataclass(slots=True)
class SourceRunStats:
    pages_fetched: int = 0
    records_found: int = 0
    records_processed: int = 0
    records_skipped: int = 0
    complete_snapshot: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceRunResult:
    organization_id: str
    source_id: str
    products: list[Product]
    stats: SourceRunStats


class ProductSource(ABC):
    organization_id: str
    source_id: str

    @abstractmethod
    def collect(self, *, max_pages: int | None = None) -> SourceRunResult:
        """Collect and normalize a snapshot from this source."""
